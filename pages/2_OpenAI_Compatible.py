import streamlit as st
import os
import tempfile
import traceback

from AutoPM3_main import query_variant_in_paper_xml


def extract_xml_content(xml_file):
    """Read XML file content and save to temp file"""
    temp_paper_file_root = "./xml_papers"
    if not os.path.exists(temp_paper_file_root):
        os.mkdir(temp_paper_file_root)

    # Read XML content
    xml_content = xml_file.read()

    # Save to temp file
    tmpfile = tempfile.NamedTemporaryFile(mode='wb', suffix='.xml', delete=False)
    tmpfile.write(xml_content)
    tmpfile.close()

    return tmpfile.name


def run_query_openai(variant_name, xml_path, api_url, model_name, api_key):
    """Run the query using OpenAI-compatible API and return results"""
    summarized_results = query_variant_in_paper_xml(
        variant_name, xml_path,
        model_name,  # model_name_table
        model_name,  # model_name_text
        api_key,
        api_url=api_url
    )
    return summarized_results


# Page config
st.set_page_config(page_title="AutoPM3 - OpenAI Compatible", page_icon="🤖")

# Inject CSS for fixed-pixel centering of the result region.
# The .result-region-marker div is emitted right before the output is rendered —
# everything that follows it in the same Streamlit vertical block gets
# constrained to a fixed `max-width` and centered. Uses the modern `:has()`
# + sibling `~` selector to scope the rule to widgets that appear *after*
# the marker (inputs/buttons above the marker stay full-width).
RESULT_REGION_CSS = """
<style>
div:has(> .result-region-marker) ~ div {
    max-width: 1200px !important;
    margin-left: auto !important;
    margin-right: auto !important;
}
</style>
"""
st.markdown(RESULT_REGION_CSS, unsafe_allow_html=True)


st.title("AutoPM3 - OpenAI Compatible 🤖")

st.markdown("""
Use this page if you want to use your own **OpenAI-compatible API endpoint**
(e.g., local models, proxy servers, or other LLM providers).
""")

secrets = st.secrets if hasattr(st, "secrets") else {}

col1, col2 = st.columns(2)
with col1:
    api_url = st.text_input('API URL', placeholder='https://api.openai.com/v1', help='OpenAI-compatible API endpoint URL',
                            value=secrets.get("openai_api_url", ""))
with col2:
    model_name = st.text_input('Model Name', placeholder='gpt-4o-mini', help='Model name to use',
                               value=secrets.get("openai_model", ""))

api_key = st.text_input('API Key', type='password', key='api_key_openai',
                         value=secrets.get("openai_api_key", ""))

st.header("Upload XML")
if st.button('Example', type='primary'):
    st.session_state.variant_name_xml_openai = 'NM_004004.5:c.71G>A'

variant_name = st.text_input('Step 1. Enter the variant (HGVS notation)', key='variant_name_xml_openai')
xml_file = st.file_uploader('Step 2. Upload XML paper', type=['xml'])

if st.button('Run', type='primary', key='run_xml_openai'):
    if xml_file and variant_name and api_url and model_name:
        try:
            xml_path = extract_xml_content(xml_file)
            summarized_results = run_query_openai(variant_name, xml_path, api_url, model_name, api_key)
            st.markdown('<div class="result-region-marker"></div>', unsafe_allow_html=True)
            st.write(summarized_results)
        except Exception as e:
            st.write('An error has occurred.')
            st.code(traceback.format_exc())
    else:
        st.write('Please enter API URL, model name, API key, variant and upload XML.')
