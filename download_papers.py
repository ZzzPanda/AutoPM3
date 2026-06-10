"""
Download papers from NCBI based on PM3_Bench_data.json
Saves XML files to ./xml_papers/{pmid}.xml
"""
import json
import os
import time
import requests
from tqdm import tqdm

def download_paper(pmid, output_dir="./xml_papers", max_retries=3):
    """Download a single paper from NCBI BioNLP API"""
    url = f'https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/{pmid}/unicode'
    output_path = os.path.join(output_dir, f"{pmid}.xml")

    # Skip if already downloaded
    if os.path.exists(output_path):
        return True, "already_exists"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    }

    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200 and 'text/xml' in response.headers.get('Content-type', ''):
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return True, "success"
        except requests.exceptions.SSLError:
            # Fallback: disable SSL verification
            try:
                response = requests.get(url, headers=headers, timeout=30, verify=False)
                if response.status_code == 200 and 'text/xml' in response.headers.get('Content-type', ''):
                    with open(output_path, 'wb') as f:
                        f.write(response.content)
                    return True, "success"
            except requests.exceptions.RequestException:
                pass
        except requests.exceptions.RequestException:
            pass

        # Wait before retry (exponential backoff)
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)

    return False, f"failed_after_{max_retries}_retries"


def main():
    # Create output directory
    output_dir = "./xml_papers"
    os.makedirs(output_dir, exist_ok=True)

    # Load PM3-Bench data
    data_file = "./PM3-Bench/PM3_Bench_data.json"
    with open(data_file, 'r') as f:
        data = json.load(f)

    # Get unique PMIDs
    pmids = set()
    for item in data:
        if 'PMID' in item:
            pmids.add(item['PMID'])

    print(f"Total unique PMIDs: {len(pmids)}")

    # Check which ones already exist
    existing = set()
    for pmid in pmids:
        if os.path.exists(os.path.join(output_dir, f"{pmid}.xml")):
            existing.add(pmid)

    print(f"Already downloaded: {len(existing)}")
    print(f"Need to download: {len(pmids) - len(existing)}")

    # Download missing papers
    to_download = [p for p in pmids if p not in existing]

    success_count = 0
    fail_count = 0
    failed_pmids = []

    print("\nDownloading papers...")
    for pmid in tqdm(to_download):
        ok, status = download_paper(pmid, output_dir)
        if ok:
            success_count += 1
        else:
            fail_count += 1
            failed_pmids.append((pmid, status))

        # Small delay to be nice to NCBI servers
        time.sleep(0.3)

    print(f"\n=== Summary ===")
    print(f"Already existed: {len(existing)}")
    print(f"Downloaded successfully: {success_count}")
    print(f"Failed to download: {fail_count}")

    if failed_pmids:
        print(f"\nFailed PMIDs:")
        for pmid, status in failed_pmids:
            print(f"  {pmid}: {status}")

        # Save failed list for retry
        failed_file = os.path.join(output_dir, "failed_pmids.json")
        with open(failed_file, 'w') as f:
            json.dump([p for p, _ in failed_pmids], f)
        print(f"\nFailed PMID list saved to: {failed_file}")


if __name__ == "__main__":
    main()