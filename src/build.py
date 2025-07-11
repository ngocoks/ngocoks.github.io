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
# URL dasar situs Anda di GitHub Pages. GANTI INI DENGAN URL REPO ANDA!
BASE_SITE_URL = "https://ngocoks.github.io" # <<< GANTI INI DENGAN DOMAIN/SUBDOMAIN GITHUB PAGES ANDA!
BLOG_NAME = "Cerita Dewasa 2025" # <<< GANTI DENGAN NAMA BLOG ANDA
# Path ke file CSS dan logo (akan di-inline atau disalin)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
CUSTOM_CSS_PATH = os.path.join(STATIC_DIR, "style.css")
LOGO_PATH = os.path.join(STATIC_DIR, "logo.png") # Pastikan logo.png ada di folder static

# File untuk menyimpan semua postingan dari Blogger dan log postingan yang sudah dipublikasikan
# --- PERBAIKAN: CACHE DISIMPAN DI ROOT ---
ALL_BLOGGER_POSTS_CACHE_FILE = "all_blogger_posts_cache.json" # Cache semua post dari Blogger
PUBLISHED_LOG_FILE = "published_posts.json" # Log ID post yang sudah dipublikasikan

# --- Konfigurasi Gemini API ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# --- Daftar Kata yang Akan Diganti/Disensor (dari build.py asli Anda) ---
REPLACEMENTS = {
    "kontol": "rudal",
    "memek": "serambi lempit",
    "ngentot": "menyetubuhi",
   "seks": "bercinta",
   "sex": "bercinta"
    # Tambahkan kata lain yang ingin disensor di sini sesuai build.py Anda
}

# --- Fungsi Utility ---
def extract_pure_text_from_html(html_content):
    """
    Ekstrak teks murni dari konten HTML, menghapus tag script dan style.
    Ini digunakan untuk mendapatkan teks asli (belum disensor) untuk pra-pemrosesan.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    for script_or_style in soup(["script", "style"]):
        script_or_style.extract() # Hapus semua tag script dan style
    text = soup.get_text(separator=' ', strip=True)
    return text

def apply_replacements_to_pure_text(text_content):
    """
    Menerapkan penggantian kata (sensor) pada teks murni.
    Ini digunakan untuk teks yang akan dikirim ke Gemini dan untuk konten artikel final.
    """
    modified_text = text_content
    for old, new in REPLACEMENTS.items():
        # Gunakan regex untuk pencarian case-insensitive dan whole word
        modified_text = re.sub(r'\b' + re.escape(old) + r'\b', new, modified_text, flags=re.IGNORECASE)
    return modified_text

def remove_anchor_tags_and_apply_replacements_to_html(html_content):
    """
    Menghilangkan semua tag <a> dan menerapkan penggantian kata (sensor) pada teks dalam HTML.
    Ini digunakan untuk konten HTML yang siap dipublikasikan (setelah disensor).
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Hapus semua tag <a>
    for a_tag in soup.find_all('a'):
        a_tag.unwrap() # Mengganti tag <a> dengan isinya (teks tanpa link)

    # Lakukan penggantian kata pada teks di setiap elemen
    for element in soup.find_all(string=True):
        if isinstance(element, NavigableString) and element.parent.name not in ['script', 'style']:
            original_text = str(element)
            modified_text = original_text
            for old, new in REPLACEMENTS.items():
                modified_text = re.sub(r'\b' + re.escape(old) + r'\b', new, modified_text, flags=re.IGNORECASE)
            
            if modified_text != original_text:
                element.replace_with(modified_text)
                
    return str(soup) # Kembalikan HTML sebagai string

def load_custom_css():
    """
    Memuat konten CSS kustom dari file.
    """
    if os.path.exists(CUSTOM_CSS_PATH):
        with open(CUSTOM_CSS_PATH, 'r', encoding='utf-8') as f:
            return f.read()
    print(f"⚠️ Peringatan: File CSS kustom tidak ditemukan di '{CUSTOM_CSS_PATH}'.")
    return ""

def get_post_image_url(post):
    """
    Mencari URL gambar thumbnail dari postingan.
    """
    content = post.get('content', '')
    soup = BeautifulSoup(content, 'html.parser')
    img_tag = soup.find('img')
    if img_tag and img_tag.has_attr('src'):
        return img_tag['src']
    
    if post.get('images'):
        for img in post['images']:
            if img.get('url'):
                return img['url']
                
    return None

def sanitize_filename(title):
    """
    Membersihkan judul untuk digunakan sebagai nama file yang aman.
    """
    filename = re.sub(r'[^\w\-]', '_', slugify(title))
    return filename[:100]

def load_json_cache(filename):
    """Memuat data JSON dari file cache."""
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print(f"Peringatan: Gagal membaca cache {filename}. Membuat cache baru.")
                return {}
    return {}

def save_json_cache(data, filename):
    """Menyimpan data JSON ke file cache."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Cache {filename} berhasil disimpan.")

def load_published_posts_state():
    """
    Memuat ID postingan yang sudah diterbitkan dari file state.
    """
    if os.path.exists(PUBLISHED_LOG_FILE):
        with open(PUBLISHED_LOG_FILE, 'r', encoding='utf-8') as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                print(f"⚠️ Peringatan: File state '{PUBLISHED_LOG_FILE}' rusak. Membuat ulang.")
                return set()
    return set()

def save_published_posts_state(published_ids):
    """
    Menyimpan ID postingan yang sudah diterbitkan ke file state.
    """
    with open(PUBLISHED_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(published_ids), f, indent=4, ensure_ascii=False)

# --- Fungsi Edit Judul dengan Gemini AI ---
def edit_title_with_gemini(post_id, original_title):
    """
    Mengirim judul artikel ke Gemini AI untuk diedit agar lebih menarik dan SEO-friendly.
    """
    if not original_title or len(original_title.strip()) < 5:
        print(f"Judul postingan ID {post_id} terlalu pendek atau kosong untuk diedit Gemini. Melewatkan.")
        return original_title

    print(f"Mengirim judul '{original_title}' (ID: {post_id}) ke Gemini AI untuk diedit...")

    try:
        model = genai.GenerativeModel(
            model_name='gemini-1.5-flash',
            generation_config={"temperature": 0.7, "top_p": 0.9, "top_k": 40},
            safety_settings=[
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ]
        )
        
        prompt_template = f"""
        Saya memiliki sebuah judul artikel: "{original_title}".
        Tugas Anda adalah mengedit judul ini agar lebih menarik, menggugah rasa ingin tahu, relevan dengan tema 'cerita dewasa 2025', dan SEO-friendly.
        Pertahankan esensi judul aslinya, namun buatlah lebih memikat dan optimalkan untuk pencarian.
        Gunakan gaya bahasa dan pemilihan kata yang canggih dan memikat, khas seperti Gemini AI.
        Berikan HANYA judul yang sudah diedit sebagai respons Anda, tanpa teks tambahan atau tanda kutip.
        """
        
        response = model.generate_content(prompt_template)
        edited_title = response.text.strip()
        
        if edited_title.startswith('"') and edited_title.endswith('"'):
            edited_title = edited_title[1:-1]
        
        print(f"✅ Gemini AI selesai mengedit judul untuk '{original_title}' menjadi: '{edited_title}'.")
        return edited_title

    except Exception as e:
        print(f"⚠️ Gagal mengedit judul artikel '{original_title}' (ID: {post_id}) dengan Gemini AI: {e}")
        # --- PERBAIKAN: KEMBALIKAN JUDUL ASLI JIKA GEMINI GAGAL ---
        return original_title

def get_all_blogger_posts_and_preprocess(api_key, blog_id):
    """
    Mengambil semua postingan dari Blogger API dan melakukan pra-pemrosesan awal.
    Judul belum diedit Gemini di sini. Teks konten disensor untuk Gemini.
    """
    all_posts = []
    next_page_token = None
    
    while True:
        url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts?key={api_key}&fetchBodies=true"
        if next_page_token:
            url += f"&pageToken={next_page_token}"
            
        print(f"Mengambil postingan dari Blogger API... {'(lanjutan)' if next_page_token else ''}")
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            posts = data.get('items', [])
            for post in posts:
                original_title = post.get('title', 'Untitled Post')
                
                # Di sini, processed_title sementara akan sama dengan original_title.
                # Pengeditan oleh Gemini akan dilakukan nanti untuk 1 artikel yang akan dipublikasikan.
                post['processed_title'] = original_title 
                post['original_title'] = original_title
                
                # pure_text_content_for_gemini: Teks murni ASLI (tanpa sensor)
                original_pure_text = extract_pure_text_from_html(post.get('content', ''))
                post['pure_text_content_for_gemini'] = original_pure_text

                # filtered_pure_text_for_gemini_input: Teks murni yang SUDAH DISENSOR, untuk DIKIRIM ke Gemini AI
                post['filtered_pure_text_for_gemini_input'] = apply_replacements_to_pure_text(original_pure_text)

                # content_html_ready_for_pub: HTML asli yang sudah disensor dan tanpa link (fallback jika Gemini tidak mengedit)
                post['content_html_ready_for_pub'] = remove_anchor_tags_and_apply_replacements_to_html(post.get('content', ''))
                all_posts.append(post)
                
            next_page_token = data.get('nextPageToken')
            if not next_page_token:
                break
        except requests.exceptions.RequestException as e:
            print(f"Error saat mengambil postingan dari Blogger API: {e}")
            print("Tidak dapat mengambil postingan baru. Menggunakan data yang ada di cache jika tersedia.")
            # Jika API gagal, kita tidak bisa mendapatkan postingan terbaru, 
            # jadi kita akan mengandalkan data dari cache yang sudah dimuat di main()
            break 
            
    print(f"✅ Berhasil mengambil {len(all_posts)} postingan dari Blogger API.")
    return all_posts

# --- Fungsi Inti: Interaksi dengan Gemini AI untuk Konten ---
def edit_first_300_words_with_gemini(post_id, title, pure_text_to_edit):
    """
    Mengirim 300 kata pertama dari teks murni (yang sudah disensor) ke Gemini AI untuk diedit.
    """
    if not isinstance(pure_text_to_edit, str):
        print(f"Error: pure_text_to_edit bukan string untuk post ID {post_id}.")
        return ""

    words = pure_text_to_edit.split()
    
    if len(words) < 50:
        print(f"Postingan ID {post_id} terlalu pendek ({len(words)} kata) untuk diedit Gemini. Melewatkan.")
        return "" 

    text_to_send = " ".join(words[:300])

    print(f"Mengirim 300 kata pertama dari artikel '{title}' (ID: {post_id}) ke Gemini AI untuk diedit (input sudah disensor)...")

    try:
        model = genai.GenerativeModel(
            model_name='gemini-1.5-flash',
            generation_config={"temperature": 0.7, "top_p": 0.9, "top_k": 40},
            safety_settings=[
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ]
        )
        
        prompt_template = f"""
        Tugas Anda adalah menyunting (parapharse siginfikan) 300 kata pertama dari teks ini untuk menjadikannya lebih menarik, ringkas, dan optimasi SEO. Fokus pada penggunaan kata-kata yang relevan untuk tema 'cerita dewasa' dan gaya bahasa yang memikat seperti Anda (Gemini AI), namun tetap menjaga keaslian pesan dan tidak menciptakan informasi baru. Pastikan output Anda adalah teks murni, tanpa tag HTML atau Markdown.
        
        Teks artikel:
        {text_to_send}
        """
        
        response = model.generate_content(prompt_template)
        
        edited_text_from_gemini = response.text
        # Pastikan output Gemini bersih dari tag yang tidak disengaja
        cleaned_edited_text = extract_pure_text_from_html(edited_text_from_gemini) 

        print(f"✅ Gemini AI selesai mengedit 300 kata pertama untuk '{title}'.")
        return cleaned_edited_text

    except Exception as e:
        print(f"⚠️ Gagal mengedit artikel '{title}' (ID: {post_id}) dengan Gemini AI: {e}")
        # --- PERBAIKAN: KEMBALIKAN STRING KOSONG JIKA GEMINI GAGAL MENGEDIT KONTEN ---
        # Ini akan membuat logika di build_single_post_page menggunakan konten asli yang disensor
        return ""

# --- Fungsi untuk Membangun Halaman Index dan Label ---
def build_index_and_label_pages(all_published_posts_data, all_unique_labels_list):
    print("Membangun ulang halaman index dan label untuk SEMUA artikel yang diterbitkan...")

    all_published_posts_data.sort(key=lambda x: datetime.fromisoformat(x['published'].replace('Z', '+00:00')), reverse=True)

    # --- Render Halaman Index ---
    list_items_html_for_index = []
    for post in all_published_posts_data:
        # Gunakan 'processed_title' yang mungkin sudah diedit Gemini (jika artikel tersebut diterbitkan hari ini)
        # atau original_title jika artikel ini diterbitkan di siklus sebelumnya
        post_slug = sanitize_filename(post['processed_title'])
        permalink_rel = f"/{post_slug}-{post['id']}.html"
        
        snippet_for_index = post.get('description_snippet', '')
        if not snippet_for_index:
            # Prioritas: 1. processed_content_with_gemini (jika ada hasil edit Gemini)
            # 2. filtered_pure_text_for_gemini_input (teks asli yang sudah disensor)
            if post.get('processed_content_with_gemini'):
                snippet_for_index = " ".join(post['processed_content_with_gemini'].split()[:50]) + "..."
            elif post.get('filtered_pure_text_for_gemini_input'):
                snippet_for_index = " ".join(post['filtered_pure_text_for_gemini_input'].split()[:50]) + "..."
            else:
                snippet_for_index = post.get('processed_title', 'Baca lebih lanjut...')

        thumbnail_url = get_post_image_url(post)
        thumbnail_tag = ""
        if thumbnail_url:
            thumbnail_tag = f"""
            <div class="post-thumbnail">
                <img src="{thumbnail_url}" alt="{post['processed_title']}" loading="lazy">
            </div>
            """
        category_html = ""
        if post.get('labels'):
            category_html = f'<span class="category">{post["labels"][0]}</span>'
            
        list_items_html_for_index.append(f"""
        <div class="post-item">
            {thumbnail_tag}
            <div class="post-content">
                <div class="post-meta">
                    {category_html}
                </div>
                <h2><a href="{permalink_rel}">{post['processed_title']}</a></h2>
                <p>{snippet_for_index}</p>
                <p><small>By {post['author']['displayName']} - {datetime.fromisoformat(post['published'].replace('Z', '+00:00')).strftime('%d %b, %Y')}</small></p>
            </div>
        </div>
        """)
    
    index_html_content = f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{BLOG_NAME} - Beranda</title>
        <link rel="canonical" href="{BASE_SITE_URL}/">
        <meta name="description" content="Kumpulan cerita dewasa terbaru 2025 dengan gaya bahasa menarik.">
        <meta name="robots" content="index, follow">
        <meta property="og:title" content="{BLOG_NAME}">
        <meta property="og:description" content="Kumpulan cerita dewasa terbaru 2025 dengan gaya bahasa menarik.">
        <meta property="og:url" content="{BASE_SITE_URL}/">
        <meta property="og:type" content="website">
        <style>{load_custom_css()}</style>
    </head>
    <body>
        <div class="container">
            <header>
                <div class="logo-area">
                    <a href="/"><img src="/logo.png" alt="{BLOG_NAME} Logo" class="logo"></a>
                    <h1><a href="/">{BLOG_NAME}</a></h1>
                </div>
                <nav>
                    <ul>
                        <li><a href="/">Beranda</a></li>
                        <li><a href="/sitemap.xml">Sitemap</a></li>
                        <li><a href="/labels.html">Kategori</a></li>
                    </ul>
                </nav>
            </header>
            <main>
                <section class="latest-posts">
                    <h2>Artikel Terbaru</h2>
                    <div class="post-list">
                        {"".join(list_items_html_for_index)}
                    </div>
                </section>
            </main>
            <footer>
                <p>&copy; {datetime.now().year} {BLOG_NAME}. All rights reserved.</p>
            </footer>
        </div>
    </body>
    </html>
    """
    with open(os.path.join(OUTPUT_DIR, "index.html"), 'w', encoding='utf-8') as f:
        f.write(index_html_content)
    print("✅ Halaman index selesai dibangun ulang.")

    # --- Render Halaman Label ---
    for label_name in all_unique_labels_list:
        label_slug = slugify(label_name)
        label_filename = f"{label_slug}.html"
        label_output_path = os.path.join(OUTPUT_DIR, label_filename)

        permalink_rel_label = f"/{label_filename}"
        permalink_abs_label = f"{BASE_SITE_URL}{permalink_rel_label}"
        
        posts_for_this_label = [p for p in all_published_posts_data if label_name in p.get('labels', [])]
        posts_for_this_label.sort(key=lambda x: datetime.fromisoformat(x['published'].replace('Z', '+00:00')), reverse=True)

        list_items_html_label = []
        for post in posts_for_this_label:
            post_slug = sanitize_filename(post['processed_title'])
            permalink_rel = f"/{post_slug}-{post['id']}.html"

            snippet_for_label = post.get('description_snippet', '')
            if not snippet_for_label:
                if post.get('processed_content_with_gemini'):
                    snippet_for_label = " ".join(post['processed_content_with_gemini'].split()[:50]) + "..."
                elif post.get('filtered_pure_text_for_gemini_input'):
                    snippet_for_label = " ".join(post['filtered_pure_text_for_gemini_input'].split()[:50]) + "..."
                else:
                    snippet_for_label = post.get('processed_title', 'Baca lebih lanjut...')
            
            thumbnail_url = get_post_image_url(post)
            thumbnail_tag = ""
            if thumbnail_url:
                thumbnail_tag = f"""
                <div class="post-thumbnail">
                    <img src="{thumbnail_url}" alt="{post['processed_title']}" loading="lazy">
                </div>
                """
            category_html = f'<span class="category">{label_name}</span>'
            
            list_items_html_label.append(f"""
            <div class="post-item">
                {thumbnail_tag}
                <div class="post-content">
                    <div class="post-meta">
                        {category_html}
                    </div>
                    <h2><a href="{permalink_rel}">{post['processed_title']}</a></h2>
                    <p>{snippet_for_label}</p>
                    <p><small>By {post['author']['displayName']} - {datetime.fromisoformat(post['published'].replace('Z', '+00:00')).strftime('%d %b, %Y')}</small></p>
                </div>
            </div>
            """)
        
        label_page_html = f"""
        <!DOCTYPE html>
        <html lang="id">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Kategori: {label_name} - {BLOG_NAME}</title>
            <link rel="canonical" href="{permalink_abs_label}">
            <meta name="description" content="Artikel dalam kategori {label_name} di {BLOG_NAME}.">
            <meta name="robots" content="index, follow">
            <meta property="og:title" content="Kategori: {label_name} - {BLOG_NAME}">
            <meta property="og:description" content="Artikel dalam kategori {label_name} di {BLOG_NAME}.">
            <meta property="og:url" content="{permalink_abs_label}">
            <meta property="og:type" content="website">
            <style>{load_custom_css()}</style>
        </head>
        <body>
            <div class="container">
                <header>
                    <div class="logo-area">
                        <a href="/"><img src="/logo.png" alt="{BLOG_NAME} Logo" class="logo"></a>
                        <h1><a href="/">{BLOG_NAME}</a></h1>
                    </div>
                    <nav>
                        <ul>
                            <li><a href="/">Beranda</a></li>
                            <li><a href="/sitemap.xml">Sitemap</a></li>
                            <li><a href="/labels.html">Kategori</a></li>
                        </ul>
                    </nav>
                </header>
                <main>
                    <section class="category-posts">
                        <h2>Artikel dalam Kategori: {label_name}</h2>
                        <div class="post-list">
                            {"".join(list_items_html_label)}
                        </div>
                    </section>
                </main>
                <footer>
                    <p>&copy; {datetime.now().year} {BLOG_NAME}. All rights reserved.</p>
                </footer>
            </div>
        </body>
        </html>
        """
        with open(label_output_path, 'w', encoding='utf-8') as f:
            f.write(label_page_html)
        print(f"✅ Halaman kategori '{label_name}' selesai dibangun.")

# --- Fungsi untuk Membangun Halaman Postingan Individual ---
def build_single_post_page(post):
    """
    Membangun file HTML untuk satu postingan individual.
    """
    post_slug = sanitize_filename(post['processed_title']) # Menggunakan judul yang sudah diedit Gemini
    output_filename = f"{post_slug}-{post['id']}.html"
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    permalink_rel = f"/{output_filename}"
    permalink_abs = f"{BASE_SITE_URL}{permalink_rel}"
    
    edited_first_300_words_pure_text = post.get('processed_content_with_gemini', '')
    
    # Ambil sisa teks artikel dari pure_text_content_for_gemini dan SENSOR sisanya
    full_original_pure_text = post.get('pure_text_content_for_gemini', '') 
    
    final_pure_text_for_article = ""

    if edited_first_300_words_pure_text:
        print(f"Menggabungkan 300 kata hasil editan Gemini dengan sisa artikel asli (dan menyensornya) untuk '{post['processed_title']}'.")
        original_words_list = full_original_pure_text.split()
        
        if len(original_words_list) >= 300:
            remaining_original_pure_text = " ".join(original_words_list[300:])
            remaining_original_pure_text_filtered = apply_replacements_to_pure_text(remaining_original_pure_text)
            
            final_pure_text_for_article = edited_first_300_words_pure_text + "\n\n" + remaining_original_pure_text_filtered
        else:
            final_pure_text_for_article = edited_first_300_words_pure_text if edited_first_300_words_pure_text else apply_replacements_to_pure_text(full_original_pure_text)
            print(f"Artikel '{post['processed_title']}' kurang dari 300 kata, menggunakan hasil editan Gemini (jika ada) atau teks asli yang disensor.")
    else:
        # Jika Gemini tidak mengedit, gunakan seluruh teks asli yang sudah disensor dari `filtered_pure_text_for_gemini_input`
        print(f"Gemini AI tidak mengedit artikel '{post['processed_title']}'. Menggunakan teks murni asli artikel yang sudah disensor.")
        final_pure_text_for_article = post.get('filtered_pure_text_for_gemini_input', full_original_pure_text)

    temp_html_from_pure_text = ""
    for paragraph in final_pure_text_for_article.split('\n\n'):
        if paragraph.strip():
            formatted_paragraph = paragraph.replace('\n', '<br>')
            temp_html_from_pure_text += f"<p>{formatted_paragraph}</p>\n"
            
    final_article_content_html = remove_anchor_tags_and_apply_replacements_to_html(temp_html_from_pure_text)


    print(f"Membangun artikel individual: {output_filename}")
    article_html = f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{post['processed_title']} - {BLOG_NAME}</title>
        <link rel="canonical" href="{permalink_abs}">
        <meta name="description" content="{post.get('description_snippet', post['processed_title'])}">
        <meta name="robots" content="index, follow">
        <meta property="og:title" content="{post['processed_title']}">
        <meta property="og:description" content="{post.get('description_snippet', post['processed_title'])}">
        <meta property="og:url" content="{permalink_abs}">
        <meta property="og:type" content="article">
        {f'<meta property="og:image" content="{get_post_image_url(post)}">' if get_post_image_url(post) else ''}
        <style>{load_custom_css()}</style>
    </head>
    <body>
        <div class="container">
            <header>
                <div class="logo-area">
                    <a href="/"><img src="/logo.png" alt="{BLOG_NAME} Logo" class="logo"></a>
                    <h1><a href="/">{BLOG_NAME}</a></h1>
                </div>
                <nav>
                    <ul>
                        <li><a href="/">Beranda</a></li>
                        <li><a href="/sitemap.xml">Sitemap</a></li>
                        <li><a href="/labels.html">Kategori</a></li>
                    </ul>
                </nav>
            </header>
            <main>
                <article>
                    <header>
                        <h1>{post['processed_title']}</h1>
                        <p class="post-meta">
                            By {post['author']['displayName']} - 
                            {datetime.fromisoformat(post['published'].replace('Z', '+00:00')).strftime('%d %b, %Y')}
                            {f' - Kategori: {", ".join(post["labels"])}' if post.get('labels') else ''}
                        </p>
                    </header>
                    <div class="article-content">
                        {final_article_content_html}
                    </div>
                </article>
            </main>
            <footer>
                <p>&copy; {datetime.now().year} {BLOG_NAME}. All rights reserved.</p>
            </footer>
        </div>
    </body>
    </html>
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(article_html)

# --- Main Logic ---
if __name__ == "__main__":
    # --- PERBAIKAN: HAPUS SHUTIL.RMTEE ---
    # Jangan hapus folder dist di awal, karena kita akan menggunakan cache dari sana
    # shutil.rmtree(OUTPUT_DIR, ignore_errors=True) 

    # 2. Muat atau ambil semua postingan dari Blogger API
    # all_posts_preprocessed akan berisi semua post, termasuk yang sudah di-cache dengan edit Gemini
    all_posts_preprocessed = {} # Inisialisasi sebagai dictionary untuk akses mudah berdasarkan ID
    if os.path.exists(ALL_BLOGGER_POSTS_CACHE_FILE):
        print(f"Memuat semua postingan dari cache '{ALL_BLOGGER_POSTS_CACHE_FILE}'.")
        # Mengubah list of dicts menjadi dict of dicts untuk akses O(1)
        cached_list = load_json_cache(ALL_BLOGGER_POSTS_CACHE_FILE)
        all_posts_preprocessed = {p['id']: p for p in cached_list}
    
    # Ambil postingan terbaru dari Blogger API
    # Jika Blogger API gagal, get_all_blogger_posts_and_preprocess akan mengembalikan list kosong
    # dan kita akan mengandalkan data dari cache yang sudah dimuat di atas.
    new_posts_from_blogger = get_all_blogger_posts_and_preprocess(API_KEY, BLOG_ID)
    
    # Gabungkan data baru dengan data cache, data baru akan menimpa yang lama jika ID sama
    for post in new_posts_from_blogger:
        all_posts_preprocessed[post['id']] = post

    # Ubah kembali ke list untuk pemrosesan selanjutnya
    all_posts_preprocessed_list = list(all_posts_preprocessed.values())
    
    # 3. Muat state postingan yang sudah diterbitkan
    published_ids = load_published_posts_state()

    # 4. Filter postingan yang belum diterbitkan dan kumpulkan semua label unik
    unpublished_posts = []
    all_unique_labels_across_all_posts = set()

    for post in all_posts_preprocessed_list: # Gunakan list yang sudah digabungkan
        post_id_str = str(post['id'])
        if post.get('labels'):
            for label in post['labels']:
                all_unique_labels_across_all_posts.add(label)

        if post_id_str not in published_ids:
            unpublished_posts.append(post)
    
    # Bagian ini penting: Jika tidak ada artikel baru, kita tetap perlu membangun ulang index dan label
    # dengan data yang sudah ada di all_posts_preprocessed (termasuk hasil edit Gemini jika sudah pernah disimpan)
    if not unpublished_posts:
        print("Tidak ada artikel baru yang perlu diterbitkan hari ini.")
        if all_posts_preprocessed_list:
            # Pastikan processed_title pada artikel yang sudah terbit menggunakan processed_title yang TERSIMPAN di cache
            # (BUKAN original_title dari Blogger)
            all_published_posts_data = [p for p in all_posts_preprocessed_list if str(p['id']) in published_ids]
            build_index_and_label_pages(all_published_posts_data, list(all_unique_labels_across_all_posts))
        
        print("🎉 Proses Selesai! (Tidak ada artikel baru yang diterbitkan)")
        print(f"File HTML sudah ada di folder: **{OUTPUT_DIR}/**")
        exit()

    unpublished_posts.sort(key=lambda x: datetime.fromisoformat(x['published'].replace('Z', '+00:00')), reverse=True)

    # 5. Pilih satu postingan untuk diterbitkan hari ini
    post_to_publish = unpublished_posts[0]
   
    print(f"🌟 Menerbitkan artikel berikutnya: '{post_to_publish.get('original_title')}' (ID: {post_to_publish.get('id')})\n")
    
    # --- PENTING: Edit Judul oleh Gemini AI HANYA untuk artikel ini ---
    # --- PERBAIKAN: Terapkan try-except untuk edit_title_with_gemini ---
    edited_title_by_gemini = post_to_publish['original_title'] # Default ke judul asli
    try:
        edited_title_by_gemini = edit_title_with_gemini(
            post_to_publish['id'], 
            post_to_publish['original_title']
        )
    except Exception as e:
        print(f"⚠️ Gagal mengedit judul dengan Gemini AI (error di luar fungsi): {e}")
        # Judul asli akan tetap digunakan
    post_to_publish['processed_title'] = edited_title_by_gemini # Update judul yang akan dipakai

    # Lakukan pengeditan AI pada teks murni yang SUDAH DISENSOR yang disiapkan untuk Gemini (hanya 300 kata pertama)
    # --- PERBAIKAN: Terapkan try-except untuk edit_first_300_words_with_gemini ---
    edited_pure_text_from_gemini_300_words = "" # Default ke string kosong
    try:
        edited_pure_text_from_gemini_300_words = edit_first_300_words_with_gemini(
            post_to_publish['id'],
            post_to_publish['processed_title'], # Kirim judul yang sudah diedit ke fungsi ini untuk logging
            post_to_publish['filtered_pure_text_for_gemini_input'] # Kirim teks yang sudah disensor ke Gemini
        )
    except Exception as e:
        print(f"⚠️ Gagal mengedit konten dengan Gemini AI (error di luar fungsi): {e}")
        # Konten asli yang disensor akan tetap digunakan di build_single_post_page karena processed_content_with_gemini kosong

    post_to_publish['processed_content_with_gemini'] = edited_pure_text_from_gemini_300_words

    # --- KRUSIAL: PERBARUI OBJEK POST DALAM all_posts_preprocessed DAN SIMPAN CACHE ---
    # Temukan indeks post_to_publish dalam list all_posts_preprocessed
    # (Perhatikan, ini mungkin tidak ideal jika list sangat besar, tapi cukup untuk kasus ini)
    # --- PERBAIKAN: Menggunakan dictionary untuk update lebih efisien ---
    all_posts_preprocessed[post_to_publish['id']] = post_to_publish
            
    # Simpan seluruh all_posts_preprocessed yang sudah diperbarui kembali ke file cache
    save_json_cache(list(all_posts_preprocessed.values()), ALL_BLOGGER_POSTS_CACHE_FILE)
    print(f"✅ Cache '{ALL_BLOGGER_POSTS_CACHE_FILE}' diperbarui dengan data Gemini AI.")

    # 6. Hasilkan file HTML untuk postingan yang dipilih
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    build_single_post_page(post_to_publish)

    # 7. Tambahkan ID postingan ke daftar yang sudah diterbitkan dan simpan state
    published_ids.add(str(post_to_publish['id']))
    save_published_posts_state(published_ids)
    print(f"✅ State file '{PUBLISHED_LOG_FILE}' diperbarui.")
    
    # 8. Bangun ulang halaman index dan label dengan SEMUA artikel yang sudah diterbitkan.
    # Sekarang, all_posts_preprocessed sudah berisi data yang diedit Gemini jika ada.
    # Dan tidak ada lagi baris yang mengembalikan processed_title ke original_title di sini.
    all_published_posts_data = [p for p in all_posts_preprocessed_list if str(p['id']) in published_ids]
    
    build_index_and_label_pages(all_published_posts_data, list(all_unique_labels_across_all_posts))
   
    print("\n🎉 Proses Selesai!")
    print(f"File HTML sudah ada di folder: **{OUTPUT_DIR}/**")
    print("GitHub Actions akan melakukan commit dan push file-file ini ke repositori Anda.")
