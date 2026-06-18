from langchain.text_splitter import RecursiveCharacterTextSplitter,CharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain.chains import RetrievalQA
from langchain import PromptTemplate
from langchain.globals import set_verbose, set_debug
import requests

from bioc import biocxml
from lxml import etree
import io
# Import the following stuff for implementing custom retrievers
from typing import List, Dict, Optional
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from app.core.table_functions import table_extraction_with_deepseek
from app.core.utils import extractTablesFromXML
from app.prompts import PM3_ANSWER

set_debug(False)


# Captured by VariantSpecificRetriever during a query and rendered by
# format_mutalyzer_diagnostics() at the end of query_variant_in_paper_xml().
# Reset at the start of each query so a stale dict from a previous run can't
# leak into the output. Keys are intentionally permissive — downstream
# format_mutalyzer_diagnostics() falls back to "n/a" for missing entries.
mutalyzer_diagnostics = {
    "input_hgvs": None,
    "var_dna": None,
    "mutalyzer": {
        "endpoint": None,
        "raw_protein_description": None,
        "protein_after_p_strip": None,
        "trimmed_long": None,
        "trimmed_short": None,
        "c_protein_id_digits": None,
        "status": "not_run",
        "error": None,
    },
    "dna_search": {
        "regex_pattern": None,
        "matched": False,
        "chunk_count": 0,
    },
    "protein_search": {
        "long_form": None,
        "short_form": None,
        "long_matched": False,
        "short_matched": False,
        "chunk_count_long": 0,
        "chunk_count_short": 0,
    },
    "position_fallback": {
        "triggered": False,
        "dna_pattern": None,
        "protein_pattern": None,
        "matched": False,
        "chunk_count": 0,
    },
    "retriever_summary": {
        "ok": False,
        "total_chunks_returned": 0,
        "short_protein": None,
    },
}


import os
import time
import asyncio
import atexit
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Dict, Optional, Any
import sys
import glob
import json
import re
import copy
import httpx
import pandas as pd


os.environ['CURL_CA_BUNDLE'] = ''  # Fix SSL error for Mutalyzer3

# Resolve protein.txt relative to the project root (parent of app/), not CWD.
# app/core/query.py → parents[2] = project root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROTEIN_MAPPING_FILE = str(_PROJECT_ROOT / 'data' / 'protein.txt')

# enum types
VARIANT_QUERY = 0
INTRANS_QUERY = 1
C_VARIANT = 0  # c.123A>G
P_VARIANT = 1  # protein change


from func_timeout import func_set_timeout


# ---------------------------------------------------------------------------
# Async runtime (semaphore + thread pools)
# ---------------------------------------------------------------------------
# Multiple Streamlit sessions share one Python process. Without a bounded
# semaphore on the LLM call path, a few concurrent users can easily fan out
# to dozens of in-flight LLM requests, hitting upstream rate limits and
# stalling everyone. ``AUTOPM3_LLM_CONCURRENCY`` (default 4) caps in-flight
# LLM calls globally.
#
# The LLM HTTP calls are also routed through a thread pool so the GIL is
# released during network I/O — the event loop is free to schedule other
# coroutines while a DeepSeek call is in flight.
_LLM_CONCURRENCY = int(os.getenv("AUTOPM3_LLM_CONCURRENCY", "4"))

_llm_semaphore: Optional[asyncio.Semaphore] = None
_llm_thread_pool: Optional[ThreadPoolExecutor] = None
_async_runtime_initialised = False


def _init_async_runtime() -> None:
    """Lazy init for the module-level async primitives.

    Idempotent: safe to call multiple times. Must be called from inside a
    running event loop the first time so ``asyncio.Semaphore`` binds to the
    right loop. ``atexit`` shuts the pools down at process exit.

    Loop-bound state (the semaphore) is re-created whenever the current
    event loop differs from the one it was last bound to. Each
    ``asyncio.run`` call in the Streamlit click handler creates a fresh
    loop, so reusing the module-level semaphore would either raise
    ``RuntimeError: ... is bound to a different event loop`` (Python 3.11
    Docker image) or silently leak across loops. Thread pools are
    loop-agnostic and only created once.
    """
    global _llm_semaphore, _llm_thread_pool, _async_runtime_initialised
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _llm_semaphore is None or (
        current_loop is not None
        and getattr(_llm_semaphore, "_loop", None) is not current_loop
    ):
        # _loop is set on first acquire; if it doesn't match the running
        # loop, we must rebuild the semaphore. (Same loop / not yet
        # acquired: reuse.)
        _llm_semaphore = asyncio.Semaphore(_LLM_CONCURRENCY)

    if _llm_thread_pool is None:
        _llm_thread_pool = ThreadPoolExecutor(
            max_workers=_LLM_CONCURRENCY, thread_name_prefix="autopm3-llm"
        )
    _async_runtime_initialised = True


@atexit.register
def _shutdown_async_runtime() -> None:
    """Best-effort pool shutdown at process exit. Errors are swallowed."""
    for pool in (_llm_thread_pool,):
        if pool is None:
            continue
        try:
            pool.shutdown(wait=False)
        except Exception:
            pass


async def _run_blocking(fn, *args, pool=None, **kwargs):
    """Run a blocking sync callable on a thread pool.

    Releases the GIL during network I/O so the event loop can schedule
    other coroutines. ``pool`` selects the executor; defaults to the LLM
    pool. Falls back to the default executor if the requested pool isn't
    initialised yet.
    """
    if pool is None:
        pool = _llm_thread_pool
    if pool is None:
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args, **kwargs)
    return await asyncio.get_running_loop().run_in_executor(
        pool, lambda: fn(*args, **kwargs)
    )


class VariantSpecificRetriever(BaseRetriever):
    documents: List[Document]
    k: int
    protein_map: Dict[str, str]
    # Per-instance retriever results. Used to live in a module-level list
    # (`retriever_OK`) which collided between concurrent Streamlit sessions.
    # Now these are Pydantic fields on the instance, so each user session's
    # retriever state is naturally isolated.
    ok: bool = False
    chunk_count: int = 0
    short_protein: Optional[str] = None

    # Assumes "query" to be the target variant (in HGVS notation)
    def _get_relevant_documents(self, query):
        variant = query
        # Remove the contig name (NM_xxxxxx)
        target_var = variant.split(":")[-1]
        # Remove c.() from the variant notation (by default is c.(123A>G) or c.123A>G)
        var_dna = target_var.replace('c.', '').replace('(', '').replace(')', '')

        # Record the input pieces the rest of the diagnostics will refer to.
        # This happens before the Mutalyzer call so even a failed lookup leaves
        # a useful "what did we ask for" trail in the rendered block.
        mutalyzer_diagnostics["input_hgvs"] = variant
        mutalyzer_diagnostics["var_dna"] = var_dna
        mutalyzer_diagnostics["mutalyzer"]["endpoint"] = (
            f'https://mutalyzer.nl/api/normalize/{variant}?only_variants=false'
        )

        # Translate the mutation to protein change using Mutalyzer.
        # ``timeout`` is mandatory: under concurrent load Mutalyzer
        # rate-limits aggressively, and an unguarded ``requests.get``
        # would hang the Streamlit script thread indefinitely (blocking
        # the second concurrent user's button handler).
        var_protein = None
        var_protein_short = None
        try:
            r = requests.get(
                mutalyzer_diagnostics["mutalyzer"]["endpoint"],
                timeout=30,
            )
            j = r.json()
            returned_prot = j['protein']['description'].split(':')[-1]
            mutalyzer_diagnostics["mutalyzer"]["raw_protein_description"] = returned_prot
            # Remove the p.()
            m = re.match(r'p.\((.*)\)', returned_prot)
            prot = m.group(1)
            mutalyzer_diagnostics["mutalyzer"]["protein_after_p_strip"] = prot
            if len(prot) < 5:  # Too short (sometimes Mutalyzer returns something like p.(=) )
                raise Exception(f'Protein change too short: {returned_prot}')
            # Sometimes the protein mutation is like Cys1447Glnfs29 but some papers write as Cys1447fs,
            # so we remove the whole Glnfs part
            var_protein = re.sub(r'[A-Za-z]{3}fs.*', '', prot)
            # Convert the protein to short form ( -> )
            var_protein_short = var_protein
            for (k,v) in self.protein_map.items():
                var_protein_short = var_protein_short.replace(k, v)
            # Remove X and * (meaning Terminal) from the protein notation, since we don't know the paper is using which one
            var_protein = var_protein.replace('X', '').replace('*', '')
            var_protein_short = var_protein_short.replace('X', '').replace('*', '')
            mutalyzer_diagnostics["mutalyzer"]["trimmed_long"] = var_protein
            mutalyzer_diagnostics["mutalyzer"]["trimmed_short"] = var_protein_short
            mutalyzer_diagnostics["mutalyzer"]["status"] = "ok"
            #print(f'Protein : {var_protein} ({var_protein_short})')
        except KeyError as e:
            mutalyzer_diagnostics["mutalyzer"]["status"] = "error"
            mutalyzer_diagnostics["mutalyzer"]["error"] = f"KeyError: {e}"
            #print('Protein: [ERROR] Not found by Mutalyzer')
            pass
        except Exception as e:
            mutalyzer_diagnostics["mutalyzer"]["status"] = "error"
            mutalyzer_diagnostics["mutalyzer"]["error"] = str(e)
            #print(f'Protein : [ERROR] {e}')
            pass

        # Done with conversion. Now do the retrieval (= regex matching)

        retrieved_chunks = []
        # Construct the regex pattern for DNA:
        # 1. 123A>G becomes \s*123\s*A>G (allow spaces around numbers)
        # 2. Further becomes \s*123\s*123A\s*>\s*G (allow spaces around > )
        dna_pattern = re.sub('([0-9]+)', '\\\\s*\\1\\\\s*', re.escape(var_dna))
        dna_pattern = re.sub('(>)', '\\\\s*\\1\\\\s*', dna_pattern)
        dna_matcher = re.compile(dna_pattern, re.IGNORECASE)

        # Record the DNA regex the matcher actually used — this is the pattern
        # the rest of the function searches the chunks with, so the value
        # displayed in the diagnostics block must match exactly.
        mutalyzer_diagnostics["dna_search"]["regex_pattern"] = dna_pattern
        mutalyzer_diagnostics["protein_search"]["long_form"] = var_protein
        mutalyzer_diagnostics["protein_search"]["short_form"] = var_protein_short

        for chunk in self.documents:
            # Re-encode the text to get rid of those annoying Unicode \x80\x89 (whitespaces)
            text = chunk.page_content.encode('utf-8').decode('unicode_escape').encode('latin-1').decode('utf-8')
            if dna_matcher.search(text) or \
               var_protein and chunk.page_content.find(var_protein) >= 0 or \
               var_protein_short and chunk.page_content.find(var_protein_short) >= 0:
                retrieved_chunks += [ chunk ]
        # If neither DNA nor protein change could retrieve anything,
        # we resort to matching by positions only...
        if not retrieved_chunks:
            dig_dna = re.findall(r'\d+', var_dna)
            dig_protein = re.findall(r'\d+', var_protein) if var_protein else None
            dig_dna_matcher = re.compile(r'\D' + str(dig_dna[0]) + r'\D') if dig_dna else None
            dig_protein_matcher = re.compile(r'\D' + str(dig_protein[0]) + r'\D') if dig_protein else None

            mutalyzer_diagnostics["position_fallback"]["triggered"] = True
            if dig_dna:
                mutalyzer_diagnostics["position_fallback"]["dna_pattern"] = (
                    r'\D' + str(dig_dna[0]) + r'\D'
                )
            if dig_protein:
                mutalyzer_diagnostics["position_fallback"]["protein_pattern"] = (
                    r'\D' + str(dig_protein[0]) + r'\D'
                )

            for chunk in self.documents:
                if dig_dna_matcher and dig_dna_matcher.search(chunk.page_content) or \
                   dig_protein_matcher and dig_protein_matcher.search(chunk.page_content):
                   retrieved_chunks += [ chunk ]

        # Now that the final retrieved_chunks list is settled, count how many
        # of the documents actually contained a DNA vs. protein match. We split
        # on the two searches because they are reported separately in the
        # diagnostics panel.
        dna_match_count = 0
        prot_long_count = 0
        prot_short_count = 0
        for chunk in self.documents:
            text = chunk.page_content.encode('utf-8').decode('unicode_escape').encode('latin-1').decode('utf-8')
            if dna_matcher.search(text):
                dna_match_count += 1
            if var_protein and chunk.page_content.find(var_protein) >= 0:
                prot_long_count += 1
            if var_protein_short and chunk.page_content.find(var_protein_short) >= 0:
                prot_short_count += 1
        mutalyzer_diagnostics["dna_search"]["matched"] = dna_match_count > 0
        mutalyzer_diagnostics["dna_search"]["chunk_count"] = dna_match_count
        mutalyzer_diagnostics["protein_search"]["long_matched"] = prot_long_count > 0
        mutalyzer_diagnostics["protein_search"]["short_matched"] = prot_short_count > 0
        mutalyzer_diagnostics["protein_search"]["chunk_count_long"] = prot_long_count
        mutalyzer_diagnostics["protein_search"]["chunk_count_short"] = prot_short_count
        if mutalyzer_diagnostics["position_fallback"]["triggered"]:
            mutalyzer_diagnostics["position_fallback"]["matched"] = len(retrieved_chunks) > 0
            mutalyzer_diagnostics["position_fallback"]["chunk_count"] = len(retrieved_chunks)

        if len(retrieved_chunks) > 0:
            self.ok = True
        self.chunk_count = len(retrieved_chunks)
        self.short_protein = var_protein_short

        mutalyzer_diagnostics["retriever_summary"]["ok"] = bool(self.ok)
        mutalyzer_diagnostics["retriever_summary"]["total_chunks_returned"] = len(retrieved_chunks)
        mutalyzer_diagnostics["retriever_summary"]["short_protein"] = var_protein_short
        return retrieved_chunks[:self.k]


# Template for the per-call diagnostics dict. The function-level
# ``mutalyzer_diagnostics`` is reset to a deep copy of this at the start of
# every ``query_variant_in_paper_xml`` call so values from a prior run don't
# bleed into the next run's rendered output.
MUTALYZER_DIAGNOSTICS_TEMPLATE: Dict[str, Any] = {
    "input_hgvs": None,
    "var_dna": None,
    "mutalyzer": {
        "endpoint": None,
        "raw_protein_description": None,
        "protein_after_p_strip": None,
        "trimmed_long": None,
        "trimmed_short": None,
        "c_protein_id_digits": None,
        "status": "not_run",
        "error": None,
    },
    "dna_search": {
        "regex_pattern": None,
        "matched": False,
        "chunk_count": 0,
    },
    "protein_search": {
        "long_form": None,
        "short_form": None,
        "long_matched": False,
        "short_matched": False,
        "chunk_count_long": 0,
        "chunk_count_short": 0,
    },
    "position_fallback": {
        "triggered": False,
        "dna_pattern": None,
        "protein_pattern": None,
        "matched": False,
        "chunk_count": 0,
    },
    "retriever_summary": {
        "ok": False,
        "total_chunks_returned": 0,
        "short_protein": None,
    },
}


def _reset_mutalyzer_diagnostics() -> None:
    """Reset the module-level diagnostics dict to its template state.

    Called at the start of each ``query_variant_in_paper_xml`` invocation.
    The dict is mutated in place so the retriever (which only sees the
    module-level binding) keeps writing into the same object — it just
    starts with clean defaults.

    NOTE: this only protects against stale state between *sequential* runs.
    Two concurrent users still race on this dict. The per-call isolation
    fix (passing a per-call dict through the retriever) is a follow-up.
    """
    mutalyzer_diagnostics.clear()
    mutalyzer_diagnostics.update(copy.deepcopy(MUTALYZER_DIAGNOSTICS_TEMPLATE))


class StaticRetriever(BaseRetriever):
    """A retriever that always returns a fixed list of documents.

    Used inside the parallel text-query fan-out: the real retriever is run
    *once* per variant before the gather to decide what chunks are
    relevant, then each parallel LLM call wraps those chunks in a
    ``StaticRetriever`` so the chain doesn't re-invoke (and re-mutate) the
    real retriever's per-instance state. This is what eliminates the
    ``self.ok`` race that 4 concurrent chain calls would otherwise create.
    """

    docs: List[Document]

    def _get_relevant_documents(self, query):  # noqa: D401 - BaseRetriever API
        return self.docs


# Load the protein abbreviatioon map from a file
def load_protein_map(filename):
    with open(filename, 'r') as f:
        lines = f.read().splitlines()
    m = { x.split()[0]: x.split()[1] for x in lines }
    return m


# Load paper from XML file
def load_xml_paper(filename, filter_tables=False):
    out_doc = ''
    # Preprocess XML to remove invalid element names (lxml is strict)
    # Remove control characters and invalid XML characters
    with open(filename, 'rb') as fp:
        content = fp.read()
    content = re.sub(rb'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', b'', content)

    # Try BioC format first
    fp_io = io.BytesIO(content)
    try:
        collection = biocxml.load(fp_io)
        document = collection.documents[0]
        for passage in document.passages:
            section_type = passage.infons.get('section_type', '').upper()
            if filter_tables and section_type in [ 'TABLE', 'REF', 'COMP_INT', 'AUTH_CONT', 'SUPPL' ]:
                pass  # filter away this section
            else:
                out_doc += passage.text + '\n'
    except Exception:
        # Fallback: custom XML format - extract text from sections
        try:
            tree = etree.fromstring(content)
            # For custom format with <main_content><section><content>...</content></section></main_content>
            # Try without namespace first
            for elem in tree.iter():
                if elem.tag in ('content', 'abstract', 'text'):
                    if elem.text:
                        out_doc += elem.text + '\n'
                # Also get text from nested sections
                if elem.tag == 'section':
                    for child in elem.iter():
                        if child.tag == 'content' and child.text:
                            out_doc += child.text + '\n'
                # Handle main_content
                if elem.tag == 'main_content':
                    text = etree.tostring(elem, method='text', encoding='unicode')
                    out_doc += text + '\n'
        except Exception as e:
            print(f"Error parsing XML: {e}")
            # Last resort: try to extract text directly
            text = tree if isinstance(tree, str) else etree.tostring(tree, method='text', encoding='unicode')
            out_doc = text

    return out_doc


def load_markdown_paper(filename: str) -> str:
    """Load Markdown / plain text papers produced by MinerU or similar tools."""
    with open(filename, "r", encoding="utf-8", errors="replace") as fp:
        return fp.read()


def extract_tables_from_markdown(markdown_text: str) -> list[pd.DataFrame]:
    """Extract simple pipe-style Markdown tables into DataFrames.

    This intentionally covers the common MinerU Markdown output shape. More
    complex HTML tables can be added later without affecting the text path.
    """
    tables: list[pd.DataFrame] = []
    block: list[str] = []

    def flush_block() -> None:
        nonlocal block
        if len(block) < 2:
            block = []
            return
        header = [cell.strip() for cell in block[0].strip().strip("|").split("|")]
        rows: list[list[str]] = []
        for line in block[1:]:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells):
                continue
            if len(cells) == len(header):
                rows.append(cells)
        if header and rows:
            tables.append(pd.DataFrame(rows, columns=header))
        block = []

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if line.startswith("|") and line.endswith("|") and line.count("|") >= 2:
            block.append(line)
        else:
            flush_block()
    flush_block()
    return tables



def split_docs(documents,chunk_size=1500,chunk_overlap=100):
# Responsible for splitting the documents into several chunks
    
    # Initializing the RecursiveCharacterTextSplitter with
    # chunk_size and chunk_overlap
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap
    )
    
    # Splitting the documents into chunks
    chunks = text_splitter.split_documents(documents=documents)
    for i, chunk in enumerate(chunks, start=1):
        chunk.metadata = {
            **(chunk.metadata or {}),
            "chunk_index": i,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
        }
    
    # returning the document chunks
    return chunks


def _normalize_chunk_text(text: str, max_chars: int = 1800) -> str:
    """Compact a chunk for evidence display without changing its content."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _evidence_id_for_doc(doc: Document) -> str:
    idx = doc.metadata.get("chunk_index", "unknown") if doc.metadata else "unknown"
    return f"chunk-{idx}"


def _evidence_from_doc(doc: Document, *, reason: str, query_variant: str) -> dict[str, Any]:
    metadata = doc.metadata or {}
    return {
        "id": _evidence_id_for_doc(doc),
        "kind": "text_chunk",
        "title": f"Chunk {metadata.get('chunk_index', '?')}",
        "reason": reason,
        "query_variant": query_variant,
        "source": metadata.get("source", "local"),
        "chunk_index": metadata.get("chunk_index"),
        "page": metadata.get("page"),
        "text": _normalize_chunk_text(doc.page_content),
        "raw_text": doc.page_content,
    }


def _append_unique_evidence(
    evidence_by_id: dict[str, dict[str, Any]],
    docs: List[Document],
    *,
    reason: str,
    query_variant: str,
) -> list[str]:
    ids: list[str] = []
    for doc in docs:
        ev = _evidence_from_doc(doc, reason=reason, query_variant=query_variant)
        if ev["id"] not in evidence_by_id:
            evidence_by_id[ev["id"]] = ev
        ids.append(ev["id"])
    return ids





# Creating the chain for Question Answering
def load_qa_chain(retriever, llm, prompt):

    return RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever, # here we are using the vectorstore as a retriever
        chain_type="stuff",
        return_source_documents=True, # including source documents in output
        chain_type_kwargs={'prompt': prompt, "verbose": False} # customizing the prompt
    )




# Prettifying the response
@func_set_timeout(300)
def get_answers_PM3(query, chain):

    # Getting response from chain
    input_dict = {'query': query}

    response = chain(input_dict)
    
    return response

def loadTextModel(model_name, api_key):
    print(f"Loading model: {model_name}")
    from langchain_deepseek import ChatDeepSeek
    llm_a = ChatDeepSeek(
        model=model_name,
        api_key=api_key,
        temperature=0.0,
        top_p=0.9,
    )
    print("Loading model DONE")
    return llm_a

def main():
    parser = ArgumentParser(description='AutoPM3')
    parser.add_argument(
        '--query_variant',
        help="query variant in HGVS format",
        required=True,
    )
    parser.add_argument(
        '--paper_path',
        help="paper_path of the query literature",
        required=True,
    )
    parser.add_argument(
        '--deepseek_api_key',
        help="DeepSeek API key",
        required=True,
    )


    # print help message if no argument input
    if len(sys.argv) <= 1 or sys.argv[1] == "-h" or sys.argv[1] == "--help":
        parser.print_help(sys.stderr)
        sys.exit(0)

    args = parser.parse_args()
    results = query_variant_in_paper_xml_sync(
        args.query_variant, args.paper_path,
        'deepseek-chat', 'deepseek-chat',
        args.deepseek_api_key
    )
    print(results)


def query_variant_in_paper_xml_sync(*args, **kwargs):
    """Sync wrapper around the async ``query_variant_in_paper_xml``.

    Used by the CLI (``main()``) and by any caller that doesn't already
    have a running event loop. Internally calls ``asyncio.run`` on a fresh
    loop, so it cannot be called from inside an async context.
    """
    return asyncio.run(query_variant_in_paper_xml(*args, **kwargs))


def _build_llm(model_name_text, api_key, api_url):
    """Construct the LLM client (sync). Returns the LLM object.

    Centralised so the ``query_variant_in_paper_xml`` body stays focused on
    flow control and the timeout-retry path can rebuild the LLM the same
    way.
    """
    if api_url:
        from langchain_openai import ChatOpenAI
        print(f"Loading OpenAI-compatible model: {model_name_text} at {api_url}")
        return ChatOpenAI(
            model=model_name_text,
            api_key=api_key,
            base_url=api_url,
            temperature=0.0,
            top_p=0.9,
        )
    return loadTextModel(model_name_text, api_key)


async def query_variant_in_paper_xml(
    query_variant,
    xml_path,
    model_name_table,
    model_name_text,
    api_key=None,
    api_url=None,
    include_evidence: bool = False,
    allow_markdown: bool = False,
):
    """Async query pipeline. See module docstring for the high-level flow.

    Concurrency model:
        * Module-level semaphore caps in-flight LLM calls to
          ``AUTOPM3_LLM_CONCURRENCY`` (default 4).
        * LLM HTTP calls run on a thread pool so the GIL is released during
          network I/O.
        * Table queries fan out via ``asyncio.gather`` (one coroutine per
          table).
        * Text queries do retrieval once per variant, then fan out up to 4
          LLM calls (variant_alias × {VARIANT_QUERY, INTRANS_QUERY}) in
          parallel.
        * Per-coroutine state (LLM response, ``text_*`` accumulators) is
          kept local to the coroutine until the gather completes; final
          merging happens after the gather so no shared-list mutation
          races.
    """
    _init_async_runtime()
    _reset_mutalyzer_diagnostics()

    llm_a = _build_llm(model_name_text, api_key, api_url)

    # Read protein abbreviation table
    protein_map = load_protein_map(PROTEIN_MAPPING_FILE)

    # check if the query variant is in the correct format (TODO)
    c_variant = query_variant.split(":")[-1]

    paper_fn = xml_path

    if not os.path.exists(paper_fn):
        print('Paper not found. Abort.')
        sys.exit(-1)
    if paper_fn.lower().endswith(".pdf"):
        print('PDF uploads are not supported. Please upload an XML paper.')
        sys.exit(-1)
    paper_suffix = Path(paper_fn).suffix.lower()
    is_markdown_input = paper_suffix in {".md", ".markdown", ".txt"}
    is_xml_input = paper_suffix == ".xml"
    if is_markdown_input and not allow_markdown:
        print('Markdown uploads are only supported by the Markdown Evidence page.')
        sys.exit(-1)
    if not (is_xml_input or (allow_markdown and is_markdown_input)):
        print('Unsupported paper format. Please upload an XML paper.')
        sys.exit(-1)

    # Load the paper and filter away tables for XML. Markdown is already the
    # display-friendly form we want to chunk and show as linked evidence.
    doc_filtered = (
        load_markdown_paper(paper_fn)
        if is_markdown_input
        else load_xml_paper(paper_fn, filter_tables=True)
    )
    doc_wrapper = [Document(page_content=doc_filtered, metadata={'source': 'local'})]
    doc_chunks = split_docs(doc_wrapper)
    # Try our custom retriever
    variant_retriever = VariantSpecificRetriever(documents=doc_chunks, k=5, protein_map=protein_map)
    variant_hgvs = query_variant

    # Mutalyzer lookup. The sync version used ``requests``; we move to
    # ``httpx.AsyncClient`` so the network I/O doesn't block the loop.
    # Same fallback semantics: on any exception we set ``protein = None``
    # and let downstream code skip the protein path.
    protein = None
    c_protein_id: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f'https://mutalyzer.nl/api/normalize/{query_variant}?only_variants=false'
            )
            r.raise_for_status()
            j = r.json()
            protein = j['protein']['description'].split(':')[-1]
            if protein == 'p.(=)':
                raise Exception('invalid notation')
            c_protein_id = re.findall(r"\d+", protein)
            mutalyzer_diagnostics["mutalyzer"]["c_protein_id_digits"] = c_protein_id
    except Exception as e:
        protein = None
        c_protein_id = []

    ##########################
    # Do table queries first #
    ##########################
    table_src_contains_variant = False
    table_query_results = []

    # XML parsing is sync; run it on the LLM thread pool so the event
    # loop isn't blocked.
    if is_markdown_input:
        relevant_tables = extract_tables_from_markdown(doc_filtered)
    else:
        relevant_tables = await _run_blocking(extractTablesFromXML, paper_fn)
    c_variant_id = None
    c_max = 0
    c_tmp_digit = re.findall(r"\d+", c_variant)
    for c_digit in c_tmp_digit:
        if len(c_digit) > c_max:  # 3
            c_variant_id = c_digit
            c_max = len(c_digit)

    table_results_plaintext: List[str] = []
    if relevant_tables:
        variant_alias = (
            [c_variant_id, c_protein_id[0]]
            if protein is not None and len(c_protein_id) > 0
            else [c_variant_id]
        )

        # Table extraction is now async; it internally fans out one
        # coroutine per table and gates them through the LLM semaphore.
        table_query_return = await table_extraction_with_deepseek(
            relevant_tables,
            query_variant_list=variant_alias,
            model_name=model_name_table,
            api_key=api_key,
            api_url=api_url,
        )

        if table_query_return is not None:
            (table_query_results, table_src_contains_variant) = table_query_return[:2]
            for c_cmd in table_query_results:
                for c_answer in c_cmd[1]:
                    if not isinstance(c_answer, tuple):
                        try:
                            table_results_plaintext.append(c_answer['plainText'])
                        except Exception:
                            pass
    else:
        table_results_plaintext = ["No table found"]
    ###########################
    # Now do the text queries #
    ###########################

    # We use "protein" instead of "c_protein_id[0]" for text.
    #   - "protein": The protein change returned by Mutalzyer
    #   - "c_protein_id[0]": Only the digits in "protein"
    variant_alias = (
        [c_variant, protein]
        if protein is not None and len(c_protein_id) > 0
        else [c_variant]
    )

    text_variant_hit = False
    text_intrans_list: List[str] = []
    text_src_contains_variant = False
    text_variant_answer = ""
    text_variant_evidence_ids: list[str] = []
    text_intrans_evidence_ids: list[str] = []

    MAX_RETRIES = 1  # number of retries before giving up
    LLM_TIMEOUT_SECONDS = 300

    # Pre-compute retrievals once per variant. ``variant_retriever.ainvoke``
    # runs the (sync) retriever body in the default executor — that's
    # fine, the work is regex matching and microseconds. The point of
    # doing this BEFORE the gather is to avoid the four parallel LLM
    # coroutines all racing on the retriever's per-instance state.
    evidence_by_id: dict[str, dict[str, Any]] = {}
    pre_computed: Dict[int, tuple] = {}
    for c_index, current_variant in enumerate(variant_alias):
        variant_retriever.ok = False
        try:
            docs = await variant_retriever.ainvoke(variant_hgvs)
        except Exception:
            docs = []
        evidence_ids = (
            _append_unique_evidence(
                evidence_by_id,
                docs,
                reason=f"Retriever matched variant alias: {current_variant}",
                query_variant=query_variant,
            )
            if include_evidence
            else []
        )
        pre_computed[c_index] = (
            current_variant,
            docs,
            variant_retriever.ok,
            variant_retriever.short_protein,
            evidence_ids,
        )

    # 2x2 fan-out: each (variant, query_type) is its own coroutine, with
    # its own LLM call through the shared semaphore. The retriever
    # itself is replaced with a StaticRetriever over the pre-computed
    # docs so the LLM chain never re-invokes the real retriever and
    # never mutates its state.
    PM3_answer_prompt = PM3_ANSWER

    async def _run_text_query(c_index, query_type):
        current_variant, docs, ok, protein_short, evidence_ids = pre_computed[c_index]
        if not ok:
            return None
        if query_type == VARIANT_QUERY:
            predefined_query = (
                f"Does the paper mention the queried variant ({current_variant}) and what is the surrounding context?"
                f"if such variant is existed, say *YES* at first otherwise say *None* (focus on variant: {current_variant})"
            )
        else:
            predefined_query = (
                f"If {current_variant} is compound heterozygous with another variant, name it; "
                f"if {current_variant} is homozygous, say homozygous; if no related variant is found, say *None*. "
                f"List all results seperated by comma and wrap the answers by *."
            )

        static = StaticRetriever(docs=docs)
        chain = load_qa_chain(
            static, llm_a,
            PM3_answer_prompt.partial(proposedQuestion=predefined_query, c_variant=current_variant),
        )

        # Per-coroutine retry: on TimeoutError, rebuild the LLM once and
        # re-invoke. The other coroutines see the rebuilt client too,
        # which matches the original sequential behaviour.
        nonlocal_llm_ref = [llm_a]
        last_exc: Optional[BaseException] = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with _llm_semaphore:
                    response = await asyncio.wait_for(
                        chain.ainvoke({"query": variant_hgvs}),
                        timeout=LLM_TIMEOUT_SECONDS,
                    )
                return {
                    "c_index": c_index,
                    "query_type": query_type,
                    "current_variant": current_variant,
                    "cur_answers": response["result"],
                    "source_documents": response["source_documents"],
                    "evidence_ids": evidence_ids,
                    "protein_short": protein_short,
                }
            except asyncio.TimeoutError as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    # Rebuild LLM for the retry (and the benefit of any
                    # other still-pending coroutines on this loop).
                    nonlocal_llm_ref[0] = _build_llm(model_name_text, api_key, api_url)
                    chain = load_qa_chain(
                        static, nonlocal_llm_ref[0],
                        PM3_answer_prompt.partial(proposedQuestion=predefined_query, c_variant=current_variant),
                    )
        return {
            "c_index": c_index,
            "query_type": query_type,
            "current_variant": current_variant,
            "cur_answers": None,
            "source_documents": [],
            "evidence_ids": evidence_ids,
            "protein_short": protein_short,
            "error": last_exc,
        }

    coros = [
        _run_text_query(c_index, query_type)
        for c_index in range(len(variant_alias))
        for query_type in (VARIANT_QUERY, INTRANS_QUERY)
    ]
    results_list = await asyncio.gather(*coros, return_exceptions=True)

    # Merge per-coroutine results into the final accumulators. Order
    # matches the original code: DNA-variant, protein-variant, then
    # in-trans queries. Because gather preserves the input order, we
    # process in input order which naturally interleaves the two
    # variants × two query types.
    for r in results_list:
        if r is None:
            continue
        if isinstance(r, BaseException):
            # Surface the exception as a skipped query — the function
            # still returns a result dict, the page renders the failure
            # via the "Variant not found in text part!" branch.
            print(f"[text query] failed: {r}")
            continue
        if r.get("error") is not None:
            print(f"[text query] timed out for {r['current_variant']}: {r['error']}")
            continue
        c_index = r["c_index"]
        query_type = r["query_type"]
        current_variant = r["current_variant"]
        cur_answers = r["cur_answers"]
        source_doc = r["source_documents"]
        evidence_ids = r.get("evidence_ids", [])
        if not cur_answers:
            continue
        text_src_contains_variant = True
        if query_type == VARIANT_QUERY:
            c_variant_inRetrieved = False
            for page in source_doc:
                c_rsids = re.findall(
                    current_variant if c_index == C_VARIANT else c_protein_id[0],
                    page.page_content,
                )
                if len(c_rsids) > 0:
                    c_variant_inRetrieved = True
            if 'yes' in cur_answers.lower():
                text_variant_hit = True
                text_variant_evidence_ids.extend(evidence_ids)
                if c_index == C_VARIANT:
                    text_variant_answer = "\n- **[DNA match result]**:" + cur_answers
                else:
                    text_variant_answer += "\n- **[Protein match result]**:" + cur_answers
            elif text_variant_answer == "":
                text_variant_answer = "\n- **Variant not found in text part!**"
        elif query_type == INTRANS_QUERY:
            if "none" not in cur_answers.lower() or "contain" in cur_answers.lower():
                text_intrans_evidence_ids.extend(evidence_ids)
                # Flatten the LLM's free-form answer into individual variant
                # lines. The model often packs multiple variants into a single
                # comma-separated sentence (e.g. "*c.269T>C*, *c.512T>A*"),
                # and the same answer can also repeat across the DNA / protein
                # alias loops. Splitting on lines first preserves the model's
                # intended order, then the render step applies order-preserving
                # dedup on a normalised form of each line.
                for line in cur_answers.splitlines():
                    stripped = line.strip()
                    if stripped:
                        text_intrans_list.append(stripped)

    table_results_plaintext_output = [str(xx).strip("\n") + "\n\n" for xx in table_results_plaintext]
    text_variant_evidence_ids = list(dict.fromkeys(text_variant_evidence_ids))
    text_intrans_evidence_ids = list(dict.fromkeys(text_intrans_evidence_ids))
    # Build the structured output consumed by render_result() in the Streamlit
    # pages. Returns a dict with the same three blocks that the old
    # markdown-string version produced, plus a fourth "Mutalyzer & Search
    # Diagnostics" block fed from the global mutalyzer_diagnostics dict that
    # VariantSpecificRetriever populated during the query. The CLI path
    # (__main__ → main() → print(results)) still works because dicts print
    # fine in the terminal.
    results = {
        "title": "Output Summary",
        "sections": [
            {
                "title": "Query Variant and Relative Intrans-variant / Genotype Found in PaperTables",
                "body": "".join([str(xx) for xx in table_results_plaintext_output]),
                **({"evidence_ids": []} if include_evidence else {}),
            },
            {
                "title": "Query Variant Found in PaperText",
                "body": (
                    f"- {text_variant_answer if text_variant_hit != '' else 'Variant not found in text part!'}"
                ),
                **({"evidence_ids": text_variant_evidence_ids} if include_evidence else {}),
            },
            {
                "title": "Query Variant's Intrans-variant Found in PaperText",
                "body": (
                    # Dedupe on a normalised form (stripped + lowercased +
                    # outer-* wrapper stripped) so cosmetic variants like
                    # "*c.269T>C*" vs "c.269T>C " don't create false
                    # duplicates across the DNA / protein alias loops.
                    # First-seen order is preserved, matching the model's
                    # original sequence of mentions. ``dict.fromkeys`` doesn't
                    # accept a key fn, so we walk the list manually with a
                    # seen-set keyed on the normalised form.
                    _format_deduped_lines(text_intrans_list)
                    if text_variant_answer != "Variant not found in text part!" and text_intrans_list
                    else "None!"
                ),
                **({"evidence_ids": text_intrans_evidence_ids} if include_evidence else {}),
            },
            {
                "title": "Mutalyzer & Search Diagnostics",
                "body": format_mutalyzer_diagnostics(mutalyzer_diagnostics),
                **({"evidence_ids": list(evidence_by_id.keys())} if include_evidence else {}),
            },
        ],
    }
    if include_evidence:
        results["evidence"] = list(evidence_by_id.values())
        if is_markdown_input:
            results["document_markdown"] = doc_filtered
    return results


def _format_deduped_lines(lines):
    """Render a list of free-form variant strings as a deduped Markdown bullet
    list.

    The intrans-variant accumulator is fed by the LLM across up to four call
    sites (DNA-aliased query + protein-aliased query, each running both
    VARIANT_QUERY and INTRANS_QUERY). The model regularly repeats the same
    variant answer across these passes, sometimes with cosmetic differences
    like a stray ``*`` wrapper, leading/trailing whitespace, or inconsistent
    capitalisation. Naively joining the raw lines produces a list with the
    same variant shown 2-4 times.

    This helper:
      1. Skips blank lines.
      2. Normalises each line (strip whitespace, lowercase, drop outer ``*``
         wrappers) to compute a dedup key.
      3. Keeps the first-seen occurrence of each key, preserving the model's
         original mention order.
      4. Renders the kept lines as ``- <original text>`` bullets, one per
         line, joined with newlines.
    """
    seen = set()
    kept = []
    for raw in lines:
        if not isinstance(raw, str):
            continue
        item = raw.strip()
        if not item:
            continue
        # Normalised key: lowercase + outer-* stripped. We don't lowercase
        # the displayed text — the model sometimes uses the case to
        # distinguish DNA (lowercase `c.`) from protein (uppercase `p.`)
        # notation and we want to keep that visible to the user.
        key = item.lower().strip("*").strip()
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return "\n".join(f"- {item}" for item in kept)


def format_mutalyzer_diagnostics(diag):
    """Render Mutalyzer/search diagnostics as Markdown.

    This helper is imported by the OpenAI-compatible Streamlit page for its
    test/demo result. Keep it tolerant of missing keys so older result payloads
    and fake diagnostics can both render.
    """
    def _section(name):
        value = diag.get(name, {})
        return value if isinstance(value, dict) else {}

    def _val(value, fallback="`n/a`"):
        return value if value not in (None, "", []) else fallback

    def _yn(value):
        return "yes" if value else "no"

    m = _section("mutalyzer")
    dna = _section("dna_search")
    prot = _section("protein_search")
    fb = _section("position_fallback")
    summ = _section("retriever_summary")

    status = m.get("status", "not_run")
    if m.get("error"):
        status = f"{status} - `{m.get('error')}`"

    lines = [
        "### 1. Input",
        f"- **HGVS variant:** `{_val(diag.get('input_hgvs'))}`",
        f"- **DNA portion (search key):** `{_val(diag.get('var_dna'))}`",
        "",
        "### 2. Mutalyzer API call",
        f"- **Endpoint:** `{_val(m.get('endpoint'))}`",
        f"- **Status:** {status}",
        f"- **Raw `protein.description`:** `{_val(m.get('raw_protein_description'))}`",
        f"- **After stripping `p.()`:** `{_val(m.get('protein_after_p_strip'))}`",
        "",
        "### 3. Transformations",
        f"- Long protein form: `{_val(m.get('trimmed_long'))}`",
        f"- Short protein form: `{_val(m.get('trimmed_short'))}`",
        f"- Table-query position digits: `{_val(m.get('c_protein_id_digits'))}`",
        "",
        "### 4. Search Patterns",
        f"- DNA regex: `{_val(dna.get('regex_pattern'))}`",
        f"- DNA matched chunks: **{dna.get('chunk_count', 0)}** ({_yn(dna.get('matched'))})",
        f"- Protein long form: `{_val(prot.get('long_form'))}` - chunks: **{prot.get('chunk_count_long', 0)}** ({_yn(prot.get('long_matched'))})",
        f"- Protein short form: `{_val(prot.get('short_form'))}` - chunks: **{prot.get('chunk_count_short', 0)}** ({_yn(prot.get('short_matched'))})",
        "",
        "### 5. Position Fallback",
        f"- Triggered: {_yn(fb.get('triggered'))}",
        f"- DNA position regex: `{_val(fb.get('dna_pattern'))}`",
        f"- Protein position regex: `{_val(fb.get('protein_pattern'))}`",
        f"- Matched chunks: **{fb.get('chunk_count', 0)}** ({_yn(fb.get('matched'))})",
        "",
        "### 6. Retriever Summary",
        f"- OK: {_yn(summ.get('ok'))}",
        f"- Total chunks returned: **{summ.get('total_chunks_returned', 0)}**",
        f"- Short-form protein observed: `{_val(summ.get('short_protein'))}`",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
  
    main()

