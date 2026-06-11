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


def run_query(variant_name, xml_path, api_key):
    """Run the query and return results"""
    summarized_results = query_variant_in_paper_xml(
        variant_name, xml_path,
        'deepseek-chat',
        'deepseek-chat',
        api_key
    )
    return summarized_results


# Main
st.title('AutoPM3')

api_key = st.text_input('DeepSeek API Key', type='password', key='api_key')

st.header("Upload XML")
if st.button('Example', type='primary'):
    st.session_state.variant_name_xml = 'NM_004004.5:c.71G>A'

variant_name = st.text_input('Step 1. Enter the variant (HGVS notation)', key='variant_name_xml')
xml_file = st.file_uploader('Step 2. Upload XML paper', type=['xml'])

if st.button('Run', type='primary', key='run_xml'):
    if xml_file and variant_name:
        try:
            xml_path = extract_xml_content(xml_file)
            summarized_results = run_query(variant_name, xml_path, api_key)
            st.write(summarized_results)
        except Exception as e:
            st.write('An error has occurred.')
            st.code(traceback.format_exc())
    else:
        st.write('Please enter variant and upload XML.')