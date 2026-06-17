import streamlit as st
import traceback

from AutoPM3_main import query_variant_in_paper_xml
from streamlit_helpers import (
    config_value,
    extract_paper_content,
    render_result,
    run_async_query,
)


def run_query(variant_name, xml_path, api_key):
    """Run the query and return results."""
    summarized_results = run_async_query(
        query_variant_in_paper_xml,
        variant_name, xml_path,
        'deepseek-chat',
        'deepseek-chat',
        api_key,
    )
    return summarized_results


# Main
st.set_page_config(page_title="AutoPM3 - DeepSeek")
st.title('AutoPM3 - DeepSeek')

default_key = config_value("DEEPSEEK_API_KEY", "deepseek_api_key")
api_key = st.text_input('DeepSeek API Key', type='password', key='api_key', value=default_key)

st.header("Upload Paper")
if st.button('Example', type='primary'):
    st.session_state.variant_name_xml = 'NM_004004.5:c.71G>A'

variant_name = st.text_input('Step 1. Enter the variant (HGVS notation)', key='variant_name_xml')
paper_file = st.file_uploader('Step 2. Upload XML paper', type=['xml'])

if st.button('Run', type='primary', key='run_xml'):
    if paper_file and variant_name:
        try:
            paper_path = extract_paper_content(paper_file)
            summarized_results = run_query(variant_name, paper_path, api_key)
            render_result(summarized_results)
        except Exception as e:
            st.write('An error has occurred.')
            st.code(traceback.format_exc())
    else:
        st.write('Please enter variant and upload XML.')
