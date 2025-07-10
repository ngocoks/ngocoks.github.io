import requests
import json
import os
import shutil
from bs4 import BeautifulSoup, NavigableString
from slugify import slugify
from datetime import datetime, timezone
import google.generativeai as genai
import re

# --- KONFIGURASI PENTING ---
API_KEY = os.getenv("BLOGGER_API_KEY")
BLOG_ID = os.getenv("BLOGGER_BLOG_ID")
OUTPUT_DIR = "dist" # Output situs statis yang akan di-deploy ke GitHub Pages
BASE_SITE_URL = "https://ngocoks.github.io" # <<< GANTI INI DENGAN DOMAIN/SUBDOMAIN GITHUB PAGES ANDA!
BLOG_NAME = "Cerita Dewasa 2025" # <<< GANTI DENGAN NAMA BLOG ANDA
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
CUSTOM_CSS_PATH = os.path.join(STATIC_DIR, "style.css")
LOGO_PATH = os.path.join(STATIC_DIR, "logo.png") 

ALL_BLOGGER_POSTS_CACHE_FILE = "all_blogger_posts_cache.json"
PUBLISHED_LOG_FILE = "published_posts.json"

# --- Konfigurasi Gemini API ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set. Please set it in your GitHub Secrets or local environment.")
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

os.makedirs(OUTPUT_DIR, exist_ok=True)

REPLACEMENT_MAP = {
    "memek": "serambi lempit",
    "kontol": "rudal",
    "ngentot": "menggenjot",
    "vagina": "serambi lempit",
    "penis": "rudal",
    "seks": "bercinta",
    "mani": "kenikmatan",
    "sex": "bercinta"
}

# === Utilitas ===

def apply_custom_word_replacements_on_text_node(text_content):
    """Menerapkan penggantian kata khusus pada string teks."""
    processed_text = text_content
    sorted_replacements = sorted(REPLACEMENT_MAP.items(), key=lambda item: len(item[0]), reverse=True)
    for old_word, new_word in sorted_replacements:
        pattern = re.compile(r'\b' + re.escape(old_word) + r'\b', re.IGNORECASE)
        processed_text = pattern.sub(new_word, processed_text)
    return processed_text

def remove_anchor_tags_and_apply_replacements_to_html(html_content):
    """
    Menghapus semua tag <a> (hanya tag, teks di dalamnya tetap)
    dan menerapkan penggantian kata khusus pada teks di dalam HTML,
    mempertahankan tag HTML lainnya seperti <img>, <p>, <div>, dll.
    """
    if not html_content:
        return ""
    print("DEBUG: Memulai remove_anchor_tags_and_apply_replacements_to_html.")
    soup = BeautifulSoup(html_content, 'html.parser')
    for a_tag in soup.find_all('a'):
        a_tag.unwrap()
    for element in soup.find_all(string=True):
        if isinstance(element, NavigableString) and element.parent.name not in ['script', 'style']:
            original_text = str(element)
            new_text = apply_custom_word_replacements_on_text_node(original_text)
            if new_text != original_text:
                element.replace_with(new_text)
    print("DEBUG: Selesai remove_anchor_tags_and_apply_replacements_to_html.")
    return str(soup)

def extract_pure_text_from_html(html_content):
    """
    Mengekstrak teks murni dari HTML, mempertahankan struktur paragraf
    (dengan double newline), tanpa ada tag HTML sama sekali, dan tanpa gambar.
    Ini khusus untuk input ke Gemini AI.
    """
    if not html_content:
        return ""
    print("DEBUG: Memulai extract_pure_text_from_html.")
    soup = BeautifulSoup(html_content, 'html.parser')
    for script_or_style_or_img in soup(["script", "style", "img"]):
        script_or_style_or_img.decompose()
    for br_tag in soup.find_all('br'):
        br_tag.replace_with('\n')
    output_parts = []
    block_tags = ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'ul', 'ol', 'pre', 'blockquote']
    if soup.body:
        for content in soup.body.contents:
            if isinstance(content, str) and content.strip():
                output_parts.append(content.strip())
                output_parts.append('\n\n')
            elif content.name in block_tags:
                break
    for element in soup.find_all(block_tags):
        text_content = element.get_text(separator=' ', strip=True)
        if text_content:
            output_parts.append(text_content)
           
        next_s = element.next_sibling
        while next_s and (next_s.name is None or next_s.name == 'br' or (isinstance(next_s, str) and next_s.strip() == '')):
            next_s = next_s.next_sibling
        
        if next_s and next_s.name in block_tags and output_parts and not output_parts[-1].endswith('\n\n'):
            output_parts.append('\n\n')
        elif not next_s and output_parts and not output_parts[-1].endswith('\n\n'):
            output_parts.append('\n\n')
               
    clean_text = ''.join(output_parts)
    clean_text = re.sub(r'\n{2,}', '\n\n', clean_text).strip()
    print("DEBUG: Selesai extract_pure_text_from_html.")
    return clean_text

def sanitize_filename(title):
    """Membersihkan judul agar cocok untuk nama file."""
    clean_title = re.sub(r'[^\w\s-]', '', title).strip().lower()
    return re.sub(r'[-\s]+', '-', clean_title)

# --- Fungsi Edit 300 Kata Pertama dengan Gemini AI ---
def edit_first_300_words_with_gemini(post_id, post_title, pure_text_for_gemini):
    words = pure_text_for_gemini.split()
   
    if len(words) < 50:
        print(f"[{post_id}] Artikel terlalu pendek (<50 kata) untuk diedit oleh Gemini AI. Melewati pengeditan.")
        return pure_text_for_gemini
       
    first_300_words_list = words[:300]
    first_300_words_text = " ".join(first_300_words_list)

    print(f"🤖 Memulai pengeditan Gemini AI untuk artikel ID: {post_id} - '{post_title}' ({len(first_300_words_list)} kata pertama)...")
   
    try:
        prompt = (
            f"Cerita Berikut adalah cuplikan dari 300 kata pertama dari cerita utuhnya, Perbaiki tata bahasa, ejaan, dan tingkatkan keterbacaan paragraf berikut. "
            f"Paraphrase signifikan setiap kata, dan buat agar lebih mengalir sehingga 300 kata pertama ini beda dari aslinya.\n\n"
            f"**Tulis ulang paragraf ini SELALU dalam BAHASA INDONESIA yang baku dan alami.**\n\n"
            f"{first_300_words_text}"
        )
       
        print(f"DEBUG: Mengirim permintaan ke Gemini untuk ID {post_id}...")
        response = gemini_model.generate_content(prompt)
        print(f"DEBUG: Menerima respons dari Gemini untuk ID {post_id}.")

        edited_text_from_gemini = response.text
       
        print(f"✅ Gemini AI selesai mengedit bagian pertama artikel ID: {post_id}.")
       
        cleaned_edited_text = extract_pure_text_from_html(edited_text_from_gemini) 
       
        if len(words) > 300:
            remaining_original_pure_text = " ".join(words[300:])
            return cleaned_edited_text + "\n\n" + remaining_original_pure_text
        else:
            return cleaned_edited_text
       
    except Exception as e:
        print(f"❌ Error saat mengedit dengan Gemini AI untuk artikel ID: {post_id} - {e}. Menggunakan teks asli untuk bagian ini.")
        return pure_text_for_gemini

# --- Fungsi untuk memuat dan menyimpan status postingan yang sudah diterbitkan ---
def load_published_posts_state():
    """Memuat ID postingan yang sudah diterbitkan dari file state."""
    print("DEBUG: Memuat status postingan yang sudah diterbitkan.")
    if os.path.exists(PUBLISHED_LOG_FILE):
        with open(PUBLISHED_LOG_FILE, 'r') as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                print(f"Warning: {PUBLISHED_LOG_FILE} is corrupted or empty. Starting with an empty published posts list.")
                return set()
    return set()

def save_published_posts_state(published_ids):
    """Menyimpan ID postingan yang sudah diterbitkan ke file state."""
    print("DEBUG: Menyimpan status postingan yang sudah diterbitkan.")
    with open(PUBLISHED_LOG_FILE, 'w') as f:
        json.dump(list(published_ids), f)

# === Ambil semua postingan dari Blogger API ===
def get_all_blogger_posts_and_preprocess(api_key, blog_id):
    """
    Mengambil semua postingan dari Blogger API dan melakukan pre-processing awal:
    - Menghapus tag <a> dan menerapkan penggantian kata pada HTML asli (untuk publikasi)
    - Mengekstrak teks murni untuk input Gemini
    """
    all_posts = []
    next_page_token = None
    
    print("📥 Mengambil SEMUA data dari Blogger API (ini mungkin butuh waktu)...")
    while True:
        url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts"
        params = {
            "key": api_key,
            "fetchImages": True,
            "maxResults": 500,
            "fields": "items(id,title,url,published,updated,content,labels,images,author(displayName)),nextPageToken"
        }
        if next_page_token:
            params["pageToken"] = next_page_token
        try:
            print(f"DEBUG: Memulai permintaan Blogger API dengan pageToken: {next_page_token or 'None'}")
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            posts_batch = data.get("items", [])
            all_posts.extend(posts_batch)
            print(f"  > Mengambil {len(posts_batch)} postingan. Total: {len(all_posts)}")

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break
        except requests.exceptions.HTTPError as e:
            print(f"Error HTTP: {e.response.status_code} - {e.response.text}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Error jaringan atau request: {e}")
            return None
    
    processed_posts = []
    print("DEBUG: Memulai pemrosesan setiap postingan yang diambil.")
    for post in all_posts:
        original_title = post.get('title', '')
        processed_title = apply_custom_word_replacements_on_text_node(original_title)
        post['processed_title'] = processed_title

        raw_content = post.get('content', '')
        content_html_ready_for_pub = remove_anchor_tags_and_apply_replacements_to_html(raw_content)
        post['content_html_ready_for_pub'] = content_html_ready_for_pub

        pure_text_for_gemini = extract_pure_text_from_html(content_html_ready_for_pub)
        post['pure_text_content_for_gemini'] = pure_text_for_gemini
       
        snippet_text = pure_text_for_gemini
        post['description_snippet'] = snippet_text[:200].replace('\n', ' ').strip()
        if len(snippet_text) > 200:
            post['description_snippet'] += "..."
           
        processed_posts.append(post)
    print("DEBUG: Selesai memproses semua postingan yang diambil.")

    print(f"Total {len(processed_posts)} postingan berhasil diambil dan diproses awal dari Blogger.")
    
    with open(ALL_BLOGGER_POSTS_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(processed_posts, f, ensure_ascii=False, indent=2)
    print(f"Semua postingan yang sudah diproses awal disimpan ke '{ALL_BLOGGER_POSTS_CACHE_FILE}'.")
    return processed_posts

# ... (bagian lain dari fungsi-fungsi build_head_content, build_header_and_sidebar, build_footer, build_html_document, get_snippet, get_post_image_url, generate_breadcrumbs_data tidak diubah di sini, tapi harus lengkap di file Anda) ...

def build_site_for_single_post(post_to_publish, all_labels_across_all_posts):
    print("Memulai proses pembangunan situs harian untuk artikel terpilih...")
    
    if not post_to_publish:
        print("Tidak ada postingan baru untuk dipublikasikan hari ini.")
        return

    try:
        with open(CUSTOM_CSS_PATH, 'r', encoding='utf-8') as f:
            custom_css_content = f.read()
    except FileNotFoundError:
        print(f"Peringatan: File CSS '{CUSTOM_CSS_PATH}' tidak ditemukan. Menggunakan CSS kosong.")
        custom_css_content = ""

    if os.path.exists(LOGO_PATH):
        shutil.copy(LOGO_PATH, os.path.join(OUTPUT_DIR, os.path.basename(LOGO_PATH)))
        print(f"Logo '{os.path.basename(LOGO_PATH)}' disalin ke '{OUTPUT_DIR}'.")
    
    current_post_labels = set(post_to_publish.get('labels', []))
    unique_labels_for_sidebar = sorted(list(all_labels_across_all_posts)) 
    print(f"Ditemukan {len(unique_labels_for_sidebar)} label unik (untuk sidebar).")

    global_header_sidebar_html = build_header_and_sidebar(unique_labels_for_sidebar, BLOG_NAME)
    global_footer_html = build_footer(BLOG_NAME, BASE_SITE_URL)

    today_date_obj = datetime.now(timezone.utc)
    today_date_formatted_iso = today_date_obj.strftime('%Y-%m-%dT%H:%M:%SZ')
    today_date_display = today_date_obj.strftime('%d %b, %Y')

    print(f"Membangun halaman artikel untuk '{post_to_publish['processed_title']}'...")
    
    post = post_to_publish
    post_slug = sanitize_filename(post['processed_title'])
    permalink_rel = f"/{post_slug}-{post['id']}.html"
    permalink_abs = f"{BASE_SITE_URL}{permalink_rel}"
    
    original_content_html_ready_for_pub = post.get('content_html_ready_for_pub', '')
    edited_pure_text_combined = post.get('processed_content_with_gemini', '')

    final_article_content_html = ""
    print("DEBUG: Memulai logika penggabungan konten Gemini.")
    if edited_pure_text_combined and post_to_publish.get('pure_text_content_for_gemini') and \
       len(post_to_publish['pure_text_content_for_gemini'].split()) >= 50:
        
        for i, paragraph in enumerate(edited_pure_text_combined.split('\n\n')):
            if paragraph.strip():
                formatted_paragraph = paragraph.replace('\n', '<br>')
                final_article_content_html += f"<p>{formatted_paragraph}</p>\n"
            print(f"DEBUG: Memproses paragraf {i+1} untuk final HTML.") # Tambahan debug
    else:
        final_article_content_html = original_content_html_ready_for_pub
    print("DEBUG: Selesai logika penggabungan konten Gemini.")

    main_image_url = get_post_image_url(post)
    
    escaped_title = json.dumps(post['processed_title'])[1:-1]
    escaped_description = json.dumps(post.get('description_snippet', ''))[1:-1]
    escaped_author_name = json.dumps(post['author']['displayName'])[1:-1]
    escaped_blog_name = json.dumps(BLOG_NAME)[1:-1]
    
    breadcrumbs_data = generate_breadcrumbs_data(post['processed_title'], post.get('labels', []), BASE_SITE_URL)
    breadcrumbs_json = json.dumps(breadcrumbs_data)

    breadcrumbs_list_items = []
    for idx, item in enumerate(breadcrumbs_data):
        if item["item"]:
            breadcrumbs_list_items.append(f"""
            <li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">
                <a itemprop="item" href="{item["item"]}">
                    <span itemprop="name">{item["name"]}</span>
                </a>
                <meta itemprop="position" content="{item["position"]}" />
            </li>
            """)
        else:
            breadcrumbs_list_items.append(f"""
            <li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">
                <span itemprop="name">{item["name"]}</span>
                <meta itemprop="position" content="{item["position"]}" />
            </li>
            """)
    breadcrumbs_nav_html = f"""
    <nav class="breadcrumbs" aria-label="breadcrumb">
        <ol itemscope itemtype="https://schema.org/BreadcrumbList">
            {''.join(breadcrumbs_list_items)}
        </ol>
    </nav>
    """
    labels_html = ""
    if post.get('labels'):
        labels_links = [f'<a href="/{slugify(label)}.html">{label}</a>' for label in post['labels']]
        labels_html = f"<br>Labels: {', '.join(labels_links)}"

    json_ld_script = f"""
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "BlogPosting",
      "headline": "{escaped_title}",
      "image": "{main_image_url}",
      "url": "{permalink_abs}",
      "datePublished": "{today_date_formatted_iso}",
      "dateModified": "{today_date_formatted_iso}",
      "author": {{
        "@type": "Person",
        "name": "{escaped_author_name}"
      }},
      "publisher": {{
        "@type": "Organization",
        "name": "{escaped_blog_name}",
        "logo": {{
          "@type": "ImageObject",
          "url": "/logo.png"
        }}
      }},
      "description": "{escaped_description}"
    }}
    </script>
    """
    post_body_content = f"""
    {global_header_sidebar_html}
    <main class="container">
        {breadcrumbs_nav_html}
        {json_ld_script}
        <article class="article-detail">
            <header class="article-header">
                <h1>{post['processed_title']}</h1>
                <p class="article-meta">
                    Dipublikasikan pada: {today_date_display} oleh {post['author']['displayName']}
                    {labels_html}
                </p>
            </header>
            <div class="article-content">
                {final_article_content_html}
            </div>
        </article>
    </main>
    {global_footer_html}
    """
    
    post_head_html = build_head_content(
        page_title=f"{post['processed_title']} - {BLOG_NAME}",
        canonical_url=permalink_abs,
        custom_css_content=custom_css_content
    )
    full_post_html = build_html_document(post_head_html, post_body_content)
    
    output_path = os.path.join(OUTPUT_DIR, permalink_rel.lstrip('/'))
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    print(f"DEBUG: Menulis file artikel ke {output_path}")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_post_html)
    print(f"  > Artikel selesai: {permalink_rel}")

    print("Membangun ulang halaman index...")
    
    list_items_html = []
    
    category_html = ""
    if post.get('labels'):
        category_html = f'<span class="category">{post["labels"][0]}</span>'
    
    snippet_for_index = post.get('description_snippet', '')
    thumbnail_url = get_post_image_url(post)
    
    thumbnail_tag = ""
    if thumbnail_url:
        thumbnail_tag = f"""
        <div class="post-thumbnail">
            <img src="{thumbnail_url}" alt="{post['processed_title']}" loading="lazy">
        </div>
        """
    list_items_html.append(f"""
    <div class="post-item">
        {thumbnail_tag}
        <div class="post-content">
            <div class="post-meta">
                {category_html}
                </div>
            <h2><a href="{permalink_rel}">{post['processed_title']}</a></h2>
            <p>{snippet_for_index}</p>
            <p><small>By {post['author']['displayName']} - {today_date_display}</small></p>
        </div>
    </div>
    """)
        
    pagination_html = ""

    current_index_permalink_abs = f"{BASE_SITE_URL}/index.html"

    ad_banner_space_html = """
    <div class="ad-banner-space">
        Space Iklan Banner
    </div>
    """
    index_body_content = f"""
    {global_header_sidebar_html}
    <main class="container">
        <h1 class="page-title">Terbaru Hari Ini</h1>
        <div class="post-list">
            {''.join(list_items_html)}
        </div>
        {pagination_html}
        {ad_banner_space_html}
    </main>
    {global_footer_html}
    """
    index_head_html = build_head_content(
        page_title=f"{BLOG_NAME} - Hari Ini",
        canonical_url=current_index_permalink_abs,
        custom_css_content=custom_css_content
    )
    full_index_html = build_html_document(index_head_html, index_body_content)
    
    output_filename = "index.html"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    print(f"DEBUG: Menulis file index ke {output_path}")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_index_html)
    print(f"  > Halaman Index selesai dengan artikel hari ini.")

    print("Membangun halaman label untuk artikel hari ini...")
    for label_name in current_post_labels:
        label_slug = slugify(label_name)
        permalink_rel_label = f"/{label_slug}.html"
        permalink_abs_label = f"{BASE_SITE_URL}{permalink_rel_label}"
        
        posts_for_label = [post]
        
        list_items_html = []
        for p in posts_for_label:
            category_html = f'<span class="category">{p["labels"][0]}</span>' if p.get('labels') else ""
            snippet = p.get('description_snippet', '')
            thumbnail_url = get_post_image_url(p)
            post_item_permalink = f"/{sanitize_filename(p['processed_title'])}-{p['id']}.html"
            published_date_formatted = today_date_display 
            
            thumbnail_tag = f"""
            <div class="post-thumbnail">
                <img src="{thumbnail_url}" alt="{p['processed_title']}" loading="lazy">
            </div>
            """ if thumbnail_url else ""
            list_items_html.append(f"""
            <div class="post-item">
                {thumbnail_tag}
                <div class="post-content">
                    <div class="post-meta">
                        {category_html}
                        </div>
                    <h2><a href="{post_item_permalink}">{p['processed_title']}</a></h2>
                    <p>{snippet}</p>
                    <p><small>By {p['author']['displayName']} - {published_date_formatted}</small></p>
                </div>
            </div>
            """)
        label_body_content = f"""
        {global_header_sidebar_html}
        <main class="container">
            <h1 class="page-title">Postingan dengan Label: {label_name}</h1>
            <div class="post-list">
                {''.join(list_items_html)}
            </div>
        </main>
        {global_footer_html}
        """
        label_head_html = build_head_content(
            page_title=f"Label: {label_name} - {BLOG_NAME}",
            canonical_url=permalink_abs_label,
            custom_css_content=custom_css_content
        )
        full_label_html = build_html_document(label_head_html, label_body_content)
        
        output_path = os.path.join(OUTPUT_DIR, permalink_rel_label.lstrip('/'))
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        print(f"DEBUG: Menulis file label ke {output_path}")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_label_html)
        print(f"  > Halaman Label '{label_name}' selesai: {permalink_rel_label}")
    print("Proses pembangunan situs harian selesai.")


if __name__ == '__main__':
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Starting Blogger post generation process...")
    print("🚀 Mengambil semua artikel Blogger (mempertahankan HTML, menghapus tag <a>, penggantian kata).")
    print("🗓️ Tanggal postingan akan mengikuti tanggal saat ini (saat GitHub Action dijalankan).")
    print("✨ Penggantian kata khusus diterapkan pada judul dan konten.")
    print("🤖 Fitur Pengeditan 300 Kata Pertama oleh Gemini AI DIAKTIFKAN, hanya untuk **satu artikel TERBARU yang akan dipublikasikan**.")
    print("✍️ Konten artikel akhir akan menggabungkan teks yang diedit Gemini dengan HTML asli yang diizinkan.")
   
    if not API_KEY or not BLOG_ID:
        print("Error: Variabel lingkungan BLOGGER_API_KEY atau BLOGGER_BLOG_ID tidak ditemukan.")
        print("Pastikan Anda mengatur mereka di GitHub Actions secrets.")
        exit()
    
    try:
        # 1. Muat daftar postingan yang sudah diterbitkan
        published_ids = load_published_posts_state()
        print(f"Ditemukan {len(published_ids)} postingan yang sudah diterbitkan sebelumnya.")

        # 2. Ambil semua postingan dari Blogger API dan lakukan pre-processing awal saja
        all_posts_preprocessed = []
        if os.path.exists(ALL_BLOGGER_POSTS_CACHE_FILE):
            print(f"Memuat semua postingan dari cache '{ALL_BLOGGER_POSTS_CACHE_FILE}'.")
            with open(ALL_BLOGGER_POSTS_CACHE_FILE, 'r', encoding='utf-8') as f:
                all_posts_preprocessed = json.load(f)
        else:
            print(f"Cache '{ALL_BLOGGER_POSTS_CACHE_FILE}' tidak ditemukan. Mengambil semua postingan dari Blogger API...")
            all_posts_preprocessed = get_all_blogger_posts_and_preprocess(API_KEY, BLOG_ID)
            if all_posts_preprocessed is None:
                print("Gagal mengambil semua postingan. Tidak dapat melanjutkan.")
                exit()

        print(f"Total {len(all_posts_preprocessed)} artikel ditemukan dan diproses awal.")

        # Kumpulkan semua label unik dari SEMUA postingan untuk sidebar navigasi global
        all_unique_labels_across_all_posts = set()
        for post in all_posts_preprocessed:
            if 'labels' in post:
                for label in post['labels']:
                    all_unique_labels_across_all_posts.add(label)

        # 3. Filter postingan yang belum diterbitkan berdasarkan ID dari file state
        unpublished_posts = [post for post in all_posts_preprocessed if str(post['id']) not in published_ids]
        print(f"Ditemukan {len(unpublished_posts)} artikel yang belum diterbitkan.")
       
        if not unpublished_posts:
            print("\n🎉 Tidak ada artikel baru yang tersedia untuk diterbitkan hari ini. Proses selesai.")
            print("GitHub Actions akan melakukan commit jika ada perubahan pada state file (misal, pertama kali dijalankan).")
            print("Anda bisa melihat status commit terakhir di log GitHub Actions.")
            exit()

        # 4. Urutkan postingan yang belum diterbitkan dari yang TERBARU ke TERLAMA
        unpublished_posts.sort(key=lambda x: datetime.fromisoformat(x['published'].replace('Z', '+00:00')), reverse=True)

        # 5. Pilih satu postingan untuk diterbitkan hari ini (yang paling baru dari yang belum diterbitkan)
        post_to_publish = unpublished_posts[0]
       
        print(f"🌟 Menerbitkan artikel berikutnya: '{post_to_publish.get('processed_title')}' (ID: {post_to_publish.get('id')})")
       
        # Lakukan pengeditan AI pada teks murni yang disiapkan untuk Gemini
        # Ini akan mengembalikan teks murni yang sudah digabung (300 kata diedit + sisa asli)
        edited_pure_text_from_gemini_combined = edit_first_300_words_with_gemini(
            post_to_publish['id'],
            post_to_publish['processed_title'],
            post_to_publish['pure_text_content_for_gemini']
        )
        post_to_publish['processed_content_with_gemini'] = edited_pure_text_from_gemini_combined

        # 6. Hasilkan file HTML untuk postingan yang dipilih (dan update index/label pages)
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        build_site_for_single_post(post_to_publish, all_unique_labels_across_all_posts)
       
        # 7. Tambahkan ID postingan ke daftar yang sudah diterbitkan dan simpan state
        published_ids.add(str(post_to_publish['id']))
        save_published_posts_state(published_ids)
        print(f"✅ State file '{PUBLISHED_LOG_FILE}' diperbarui.")
       
        print("\n🎉 Proses Selesai!")
        print(f"File HTML sudah ada di folder: **{OUTPUT_DIR}/**")
        print("GitHub Actions akan melakukan commit dan push file-file ini ke repositori Anda.")

    except Exception as e:
        print(f"❌ Terjadi kesalahan fatal: {e}")
        import traceback
        traceback.print_exc()
