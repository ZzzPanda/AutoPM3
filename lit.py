import streamlit as st
import os
import tempfile
import requests
import traceback

from AutoPM3_main import query_variant_in_paper_xml


def extract_pdf_text(pdf_file):
    """Extract text from PDF file and convert to BioC XML format"""
    import pdfplumber

    temp_paper_file_root = "./xml_papers"
    if not os.path.exists(temp_paper_file_root):
        os.mkdir(temp_paper_file_root)

    # Extract text from PDF
    text_content = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_content.append(page_text)

    full_text = "\n\n".join(text_content)

    # Convert to BioC XML format
    bioc_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<collection>
  <source>AutoPM3</source>
  <date>2024-01-01</date>
  <key>uploaded_paper</key>
  <document>
    <id>uploaded</id>
    <passage>
      <infons>
        <section_type>ABSTRACT</section_type>
      </infons>
      <text>{full_text}</text>
    </passage>
  </document>
</collection>'''

    # Save to temp file
    tmpfile = tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False)
    tmpfile.write(bioc_xml)
    tmpfile.close()

    return tmpfile.name


def load_xml(url, pmid):
    """Load XML from NCBI API based on PMID"""
    temp_paper_file_root = "./xml_papers"
    if not os.path.exists(temp_paper_file_root):
        os.mkdir(temp_paper_file_root)
    fn = str(pmid) + ".xml"
    xml_path = os.path.join(temp_paper_file_root, fn)
    if os.path.exists(xml_path):
        return xml_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    }
    try:
        response = requests.get(url, headers=headers, timeout=30)
    except requests.exceptions.SSLError:
        # Fallback: disable SSL verification for problematic connections
        response = requests.get(url, headers=headers, timeout=30, verify=False)
    except requests.exceptions.RequestException as e:
        raise Exception(f'Failed to download paper: {e}')

    if response.status_code == 200 and 'text/xml' in response.headers.get('Content-type', ''):
        with open(xml_path, 'wb') as f:
            f.write(response.content)
        return xml_path
    else:
        raise Exception('Invalid PMID. Make sure the publication has OpenAccess.')


def run_query(variant_name, xml_path, ollama_base_url, llm_backend, api_key):
    """Run the query and return results"""
    summarized_results = query_variant_in_paper_xml(
        variant_name, xml_path,
        'sqlcoder-7b-Mistral-7B-Instruct-v0.2-slerp.Q8_0',
        'llama3_loraFT-8b-f16',
        ollama_base_url,
        llm_backend,
        api_key
    )
    return summarized_results


# Main
st.title('AutoPM3')

# Tabs for two methods
tab1, tab2 = st.tabs(["Upload PDF", "Enter PMID"])

# Common settings
llm_backend = st.selectbox('LLM Backend', ['ollama', 'deepseek'], key='llm_backend')
ollama_base_url = st.text_input('Ollama base URL', value='http://localhost:11434', key='ollama_base_url')
api_key = st.text_input('DeepSeek API Key', type='password', key='api_key')

# Tab 1: Upload PDF
with tab1:
    st.header("Upload PDF")
    if st.button('Example', type='primary'):
        st.session_state.variant_name_pdf = 'NM_004004.5:c.71G>A'

    variant_name = st.text_input('Step 1. Enter the variant (HGVS notation)', key='variant_name_pdf')
    pdf_file = st.file_uploader('Step 2. Upload PDF paper', type=['pdf'])

    if st.button('Run', type='primary', key='run_pdf'):
        if pdf_file and variant_name:
            try:
                xml_path = extract_pdf_text(pdf_file)
                summarized_results = run_query(variant_name, xml_path, ollama_base_url, llm_backend, api_key)
                st.write(summarized_results)
            except Exception as e:
                st.write('An error has occurred.')
                st.code(traceback.format_exc())
        else:
            st.write('Please enter variant and upload PDF.')

# Tab 2: Enter PMID
with tab2:
    st.header("Enter PMID")
    if st.button('Example', type='primary', key='example_pmid'):
        st.session_state.variant_name_pmid = 'NM_004004.5:c.71G>A'
        st.session_state.pmid = '15070423'

    variant_name = st.text_input('Step 1. Enter the variant (HGVS notation)', key='variant_name_pmid')

    paper_url = ''
    pmid = st.text_input('Step 2. Enter the PMID of the paper', key='pmid')
    if pmid:
        try:
            pmid = int(pmid)
            paper_url = f'https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/{pmid}/unicode'
        except ValueError:
            st.write('Invalid PMID.')

    if st.button('Run', type='primary', key='run_pmid'):
        if paper_url and variant_name:
            try:
                xml_path = load_xml(paper_url, pmid)
                summarized_results = run_query(variant_name, xml_path, ollama_base_url, llm_backend, api_key)
                st.write(summarized_results)
            except Exception as e:
                st.write('An error has occurred.')
                st.code(traceback.format_exc())
        else:
            st.write('Please enter variant and PMID.')