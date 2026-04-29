import os
import re
import shutil
import zipfile
import webbrowser
from urllib.parse import urljoin, urlparse, unquote
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Set a realistic User-Agent to avoid being blocked by some sites
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def sanitize_filename(url_path: str) -> str:
    """Convert a URL path to a safe local file path."""
    path = unquote(url_path)
    # Remove query strings and fragments
    path = path.split('?')[0].split('#')[0]
    # Replace unsafe characters
    safe = re.sub(r'[<>:"/\\|?*]', '_', path)
    # If it's a directory path (ends with /), add index.html
    if safe.endswith('/') or safe == '':
        safe += 'index.html'
    return safe

def download_resource(url: str, folder: str, session: requests.Session) -> str:
    """
    Download a resource and save it locally inside 'folder'.
    Returns the relative local path to be used in the HTML.
    """
    try:
        resp = session.get(url, stream=True, timeout=10, verify=False)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [!] Failed to download {url}: {e}")
        return None

    # Build a local path that preserves the original URL structure
    parsed = urlparse(url)
    local_rel_path = sanitize_filename(parsed.path)
    if not local_rel_path:
        local_rel_path = "index.html"
    local_full_path = os.path.join(folder, local_rel_path)

    # Create subdirectories if needed
    os.makedirs(os.path.dirname(local_full_path), exist_ok=True)

    # Write the file
    with open(local_full_path, 'wb') as f:
        for chunk in resp.iter_content(1024):
            f.write(chunk)

    return local_rel_path

def main():
    # Disable SSL warnings (optional, for sites with self-signed certs)
    requests.packages.urllib3.disable_warnings()

    # 1. Get URL from the user
    url = input("Enter the full URL of the page (e.g., https://example.com): ").strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    print(f"\n[*] Downloading page: {url}")

    # Create a session for persistent connections and cookies
    session = requests.Session()
    session.headers.update(HEADERS)

    # 2. Download the main HTML page
    try:
        main_response = session.get(url, timeout=15, verify=False)
        main_response.raise_for_status()
    except Exception as e:
        print(f"Error fetching the page: {e}")
        return

    # Determine the local folder name (based on domain + a short path)
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.replace(':', '_')  # replace colon for port numbers
    page_path = sanitize_filename(parsed_url.path.strip('/'))
    folder_name = f"site_{domain}_{page_path if page_path != 'index.html' else ''}".strip('_')
    download_dir = os.path.join(os.getcwd(), folder_name)

    # Create the download folder (remove if already exists)
    if os.path.exists(download_dir):
        shutil.rmtree(download_dir)
    os.makedirs(download_dir)

    # Parse the HTML
    soup = BeautifulSoup(main_response.text, 'html.parser')

    # 3. Download all linked resources and update HTML references
    # Tags and attributes that typically point to external resources
    resource_tags = {
        'img': 'src',
        'script': 'src',
        'link': 'href',       # CSS, icons
        'source': 'src',      # <source> inside <video>/<audio>
        'video': 'poster',    # poster image for video
        'audio': 'src',
        'iframe': 'src',
        'embed': 'src',
        'object': 'data',
    }

    downloaded = set()   # avoid downloading the same URL twice
    print("[*] Downloading assets...")

    for tag_name, attr in resource_tags.items():
        for tag in soup.find_all(tag_name):
            resource_url = tag.get(attr)
            if not resource_url:
                continue

            # Convert relative URL to absolute
            absolute_url = urljoin(url, resource_url)

            # Skip non-http(s) links (data:, javascript:, mailto:, etc.)
            if not absolute_url.startswith(('http://', 'https://')):
                continue

            # Skip already processed URLs
            if absolute_url in downloaded:
                # Still update the tag to point to the local file
                local_rel = None
                # We need to know where it was saved
                # Reconstruct the relative path (same as in download_resource)
                parsed_abs = urlparse(absolute_url)
                local_rel = sanitize_filename(parsed_abs.path)
                if local_rel:
                    tag[attr] = local_rel
                continue

            downloaded.add(absolute_url)

            # Download and get local relative path
            local_path = download_resource(absolute_url, download_dir, session)
            if local_path:
                # Update the tag to point to the local file
                tag[attr] = local_path

    # 4. Save the modified HTML as index.html
    html_filename = os.path.join(download_dir, 'index.html')
    with open(html_filename, 'w', encoding='utf-8') as f:
        f.write(str(soup))

    print(f"\n[✔] Page and assets saved in: {download_dir}")

    # 5. Open the local HTML file in the default browser
    webbrowser.open('file://' + os.path.abspath(html_filename))

    # 6. Zip the entire downloaded folder
    zip_name = folder_name + '.zip'
    zip_path = os.path.join(os.getcwd(), zip_name)

    print(f"[*] Creating zip archive: {zip_name}")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(download_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(download_dir))
                zipf.write(file_path, arcname)

    # 7. Move the zip file into a folder named "page"
    page_folder = os.path.join(os.getcwd(), 'page')
    os.makedirs(page_folder, exist_ok=True)
    final_zip = os.path.join(page_folder, zip_name)

    # If a file with the same name already exists in 'page', remove it
    if os.path.exists(final_zip):
        os.remove(final_zip)

    shutil.move(zip_path, final_zip)

    print(f"[✔] Zip file stored in: {final_zip}")
    print("Done! The page has been saved and zipped successfully.")

if __name__ == "__main__":
    main()
