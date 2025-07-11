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
# Jika repo Anda adalah 'username.github.io', biarkan seperti ini.
# Jika repo Anda adalah 'username.github.io/nama-repo', ubah menjadi 'https://username.github.io/nama-repo'
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
    (Tidak digunakan dalam mode diagnostik HTML minimal)
    """
    return "" # Mengembalikan string kosong agar tidak ada CSS kustom

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
    # Menggunakan slugify untuk konversi dasar, lalu membersihkan lebih lanjut
    filename = slugify(title)
    filename = re.sub(r'[^a-z0-9\-]', '', filename) # Hanya izinkan huruf kecil, angka, dan hyphen
    return filename[:100] # Batasi panjang filename

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
    --- PERBAIKAN: Pastikan ID adalah string ---
    """
    if os.path.exists(PUBLISHED_LOG_FILE):
        with open(PUBLISHED_LOG_FILE, 'r', encoding='utf-8') as f:
            try:
                # Pastikan setiap ID diubah menjadi string saat dimuat
                return set(str(item) for item in json.load(f))
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
                
                # --- PERBAIKAN: Pastikan post ID adalah string saat disimpan ---
                post['id'] = str(post['id']) # Pastikan ID selalu string
                
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
        return ""

# --- Fungsi untuk Membangun Halaman Index dan Label ---
def build_index_and_label_pages(all_published_posts_data, all_unique_labels_list):
    print("Membangun ulang halaman index dan label untuk SEMUA artikel yang diterbitkan...")

    # --- DEBUGGING: Tampilkan urutan sebelum sorting ---
    print("\nDEBUG: Urutan postingan sebelum sorting:")
    for post in all_published_posts_data[:5]: # Tampilkan 5 post pertama
        print(f"  - {post.get('processed_title', 'N/A')} (Published: {post.get('published', 'N/A')})")

    all_published_posts_data.sort(key=lambda x: datetime.fromisoformat(x['published'].replace('Z', '+00:00')), reverse=True)

    # --- DEBUGGING: Tampilkan urutan setelah sorting ---
    print("\nDEBUG: Urutan postingan setelah sorting:")
    for post in all_published_posts_data[:5]: # Tampilkan 5 post pertama
        print(f"  - {post.get('processed_title', 'N/A')} (Published: {post.get('published', 'N/A')})")
    
    # --- Render Halaman Index ---
    list_items_html_for_index = []
    for post in all_published_posts_data:
        post_slug = sanitize_filename(post['processed_title'])
        permalink_rel = f"/{post_slug}-{post['id']}.html"
        
        print(f"DEBUG: Index link untuk '{post['processed_title']}' (ID: {post['id']}) akan menjadi: {permalink_rel}")

        snippet_for_index = post.get('description_snippet', '')
        if not snippet_for_index:
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
            <img src="{thumbnail_url}" alt="{post['processed_title']}" style="max-width: 100px; height: auto; margin-right: 10px;">
            """
        category_html = ""
        if post.get('labels'):
            category_html = f'<span>Kategori: {post["labels"][0]}</span>'
            
        list_items_html_for_index.append(f"""
        <div style="border: 1px solid #ccc; padding: 10px; margin-bottom: 10px; display: flex; align-items: center;">
            {thumbnail_tag}
            <div>
                <h3><a href="{permalink_rel}" style="color: blue; text-decoration: underline;">{post['processed_title']}</a></h3>
                <p>{snippet_for_index}</p>
                <p><small>By {post['author']['displayName']} - {datetime.fromisoformat(post['published'].replace('Z', '+00:00')).strftime('%d %b, %Y')}</small></p>
                {category_html}
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
        <style>
            body {{ font-family: sans-serif; margin: 20px; }}
            h1 {{ color: #333; }}
            a {{ text-decoration: none; }}
        </style>
    </head>
    <body>
        <h1>{BLOG_NAME} - Beranda</h1>
        <p>Selamat datang di blog kami!</p>
        <h2>Artikel Terbaru</h2>
        <div>
            {"".join(list_items_html_for_index)}
        </div>
        <footer>
            <p>&copy; {datetime.now().year} {BLOG_NAME}. All rights reserved.</p>
        </footer>
    </body>
    </html>
    """
    print(f"DEBUG: Length of generated index_html_content: {len(index_html_content)} bytes") # Debugging
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
                <img src="{thumbnail_url}" alt="{post['processed_title']}" style="max-width: 100px; height: auto; margin-right: 10px;">
                """
            category_html = f'<span>Kategori: {label_name}</span>'
            
            list_items_html_label.append(f"""
            <div style="border: 1px solid #ccc; padding: 10px; margin-bottom: 10px; display: flex; align-items: center;">
                {thumbnail_tag}
                <div>
                    <h3><a href="{permalink_rel}" style="color: blue; text-decoration: underline;">{post['processed_title']}</a></h3>
                    <p>{snippet_for_label}</p>
                    <p><small>By {post['author']['displayName']} - {datetime.fromisoformat(post['published'].replace('Z', '+00:00')).strftime('%d %b, %Y')}</small></p>
                    {category_html}
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
            <style>
                body {{ font-family: sans-serif; margin: 20px; }}
                h1 {{ color: #333; }}
                a {{ text-decoration: none; }}
            </style>
        </head>
        <body>
            <h1>Kategori: {label_name} - {BLOG_NAME}</h1>
            <div>
                {"".join(list_items_html_label)}
            </div>
            <footer>
                <p>&copy; {datetime.now().year} {BLOG_NAME}. All rights reserved.</p>
            </footer>
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

    # --- DEBUGGING: Tampilkan filename dan path yang dihasilkan ---
    print(f"DEBUG: Generating single post HTML for title='{post['processed_title']}' (ID: {post['id']})")
    print(f"DEBUG: Calculated post_slug: {post_slug}")
    print(f"DEBUG: Final output_filename: {output_filename}")
    print(f"DEBUG: Full output_path: {output_path}")

    permalink_rel = f"/{output_filename}"
    permalink_abs = f"{BASE_SITE_URL}{permalink_rel}"
    
    # --- DEBUGGING: Cek panjang konten di berbagai tahap ---
    full_original_pure_text = post.get('pure_text_content_for_gemini', '') 
    print(f"DEBUG: Original pure text length for '{post['processed_title']}': {len(full_original_pure_text)} bytes")

    edited_first_300_words_pure_text = post.get('processed_content_with_gemini', '')
    print(f"DEBUG: Edited 300 words pure text length: {len(edited_first_300_words_pure_text)} bytes")

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
        print(f"Gemini AI tidak mengedit artikel '{post['processed_title']}'. Menggunakan teks murni asli artikel yang sudah disensor.")
        final_pure_text_for_article = post.get('filtered_pure_text_for_gemini_input', full_original_pure_text)

    print(f"DEBUG: Final pure text for article length: {len(final_pure_text_for_article)} bytes")

    temp_html_from_pure_text = ""
    for paragraph in final_pure_text_for_article.split('\n\n'):
        if paragraph.strip():
            formatted_paragraph = paragraph.replace('\n', '<br>')
            temp_html_from_pure_text += f"<p>{formatted_paragraph}</p>\n"
            
    print(f"DEBUG: temp_html_from_pure_text length: {len(temp_html_from_pure_text)} bytes") # Debugging

    final_article_content_html = remove_anchor_tags_and_apply_replacements_to_html(temp_html_from_pure_text)
    print(f"DEBUG: final_article_content_html length: {len(final_article_content_html)} bytes") # Debugging


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
        <style>
            body {{ font-family: sans-serif; margin: 20px; }}
            h1 {{ color: #333; }}
            p {{ line-height: 1.6; }}
        </style>
    </head>
    <body>
        <header>
            <h1>{post['processed_title']}</h1>
            <p style="font-size: 0.9em; color: #666;">
                By {post['author']['displayName']} - 
                {datetime.fromisoformat(post['published'].replace('Z', '+00:00')).strftime('%d %b, %Y')}
                {f' - Kategori: {", ".join(post["labels"])}' if post.get('labels') else ''}
            </p>
        </header>
        <main>
            <div class="article-content">
                {final_article_content_html}
            </div>
        </main>
        <footer>
            <p>&copy; {datetime.now().year} {BLOG_NAME}. All rights reserved.</p>
        </footer>
    </body>
    </html>
    """
    print(f"DEBUG: Total article_html length for '{post['processed_title']}': {len(article_html)} bytes") # Debugging
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(article_html)

# --- Main Logic ---
if __name__ == "__main__":
    # 1. Inisialisasi dan muat cache yang sudah ada
    all_posts_preprocessed = {} 
    if os.path.exists(ALL_BLOGGER_POSTS_CACHE_FILE):
        print(f"Memuat semua postingan dari cache '{ALL_BLOGGER_POSTS_CACHE_FILE}'.")
        cached_list = load_json_cache(ALL_BLOGGER_POSTS_CACHE_FILE)
        # --- PERBAIKAN: Pastikan ID adalah string saat dimasukkan ke dictionary ---
        all_posts_preprocessed = {str(p['id']): p for p in cached_list}
    print(f"DEBUG: all_posts_preprocessed (from cache) count: {len(all_posts_preprocessed)}")

    # 2. Ambil postingan terbaru dari Blogger API dan gabungkan dengan cache
    new_posts_from_blogger = get_all_blogger_posts_and_preprocess(API_KEY, BLOG_ID)
    print(f"DEBUG: new_posts_from_blogger count: {len(new_posts_from_blogger)}")
    for post in new_posts_from_blogger:
        # --- PERBAIKAN: Pastikan ID adalah string saat dimasukkan ke dictionary ---
        all_posts_preprocessed[str(post['id'])] = post
    
    # Ubah kembali ke list untuk pemrosesan selanjutnya
    all_posts_preprocessed_list = list(all_posts_preprocessed.values())
    print(f"DEBUG: Total posts after merging (all_posts_preprocessed_list) count: {len(all_posts_preprocessed_list)}")
    
    # 3. Muat state postingan yang sudah diterbitkan
    # --- PERBAIKAN: load_published_posts_state sudah memastikan ID adalah string ---
    published_ids = load_published_posts_state()
    print(f"DEBUG: published_ids count: {len(published_ids)}")
    if len(published_ids) > 0:
        print(f"DEBUG: Sample published_ids: {list(published_ids)[:5]}")


    # 4. Identifikasi postingan yang belum diterbitkan dan kumpulkan semua label unik
    unpublished_posts = []
    all_unique_labels_across_all_posts = set()

    for post in all_posts_preprocessed_list:
        # --- PERBAIKAN: Pastikan post_id_str adalah string ---
        post_id_str = str(post['id'])
        if post.get('labels'):
            for label in post['labels']:
                all_unique_labels_across_all_posts.add(label)

        if post_id_str not in published_ids:
            unpublished_posts.append(post)
    
    print(f"DEBUG: Unpublished posts count: {len(unpublished_posts)}")
    # Urutkan postingan yang belum diterbitkan (jika ada)
    unpublished_posts.sort(key=lambda x: datetime.fromisoformat(x['published'].replace('Z', '+00:00')), reverse=True)

    # 5. Proses SATU postingan baru (jika tersedia)
    post_to_process_with_gemini = None
    if unpublished_posts:
        post_to_process_with_gemini = unpublished_posts[0]
        print(f"🌟 Menerbitkan artikel berikutnya: '{post_to_process_with_gemini.get('original_title')}' (ID: {post_to_process_with_gemini.get('id')})\n")
        
        # --- Edit Judul oleh Gemini AI ---
        edited_title_by_gemini = post_to_process_with_gemini['original_title'] # Default ke judul asli
        try:
            edited_title_by_gemini = edit_title_with_gemini(
                post_to_process_with_gemini['id'], 
                post_to_process_with_gemini['original_title']
            )
        except Exception as e:
            print(f"⚠️ Gagal mengedit judul dengan Gemini AI (error di luar fungsi): {e}")
        post_to_process_with_gemini['processed_title'] = edited_title_by_gemini # Update judul yang akan dipakai

        # --- Edit Konten oleh Gemini AI ---
        edited_pure_text_from_gemini_300_words = "" # Default ke string kosong
        try:
            edited_pure_text_from_gemini_300_words = edit_first_300_words_with_gemini(
                post_to_process_with_gemini['id'],
                post_to_process_with_gemini['processed_title'], # Kirim judul yang sudah diedit ke fungsi ini untuk logging
                post_to_process_with_gemini['filtered_pure_text_for_gemini_input'] # Kirim teks yang sudah disensor ke Gemini
            )
        except Exception as e:
            print(f"⚠️ Gagal mengedit konten dengan Gemini AI (error di luar fungsi): {e}")
        post_to_process_with_gemini['processed_content_with_gemini'] = edited_pure_text_from_gemini_300_words

        # Perbarui postingan di dictionary all_posts_preprocessed utama
        # --- PERBAIKAN: Pastikan ID adalah string saat dimasukkan ke dictionary ---
        all_posts_preprocessed[str(post_to_process_with_gemini['id'])] = post_to_process_with_gemini
        
        # Tambahkan ke published_ids
        published_ids.add(str(post_to_process_with_gemini['id']))
        save_published_posts_state(published_ids)
        print(f"✅ State file '{PUBLISHED_LOG_FILE}' diperbarui.")

    else:
        print("Tidak ada artikel baru yang perlu diedit dan diterbitkan hari ini.")

    # 6. Simpan cache all_posts_preprocessed yang sudah diperbarui (penting untuk menyimpan editan Gemini)
    save_json_cache(list(all_posts_preprocessed.values()), ALL_BLOGGER_POSTS_CACHE_FILE)
    print(f"✅ Cache '{ALL_BLOGGER_POSTS_CACHE_FILE}' diperbarui dengan data Gemini AI (jika ada).")

    # 7. Regenerasi HTML untuk SEMUA postingan yang sudah diterbitkan
    os.makedirs(OUTPUT_DIR, exist_ok=True) # Pastikan direktori dist ada

    all_published_posts_data = [p for p in all_posts_preprocessed_list if str(p['id']) in published_ids]
    print(f"DEBUG: all_published_posts_data count (for HTML regeneration): {len(all_published_posts_data)}")
    if len(all_published_posts_data) > 0:
        print(f"DEBUG: Sample all_published_posts_data titles: {[p.get('processed_title', 'N/A') for p in all_published_posts_data[:5]]}")


    if not all_published_posts_data:
        print("Tidak ada artikel yang diterbitkan sama sekali. Tidak ada halaman postingan individual yang akan dibuat.")
    else:
        print(f"Membangun ulang {len(all_published_posts_data)} halaman postingan individual...")
        for post in all_published_posts_data:
            build_single_post_page(post)
        print("✅ Semua halaman postingan individual selesai dibangun ulang.")

    # 8. Bangun halaman index dan label
    build_index_and_label_pages(all_published_posts_data, list(all_unique_labels_across_all_posts))
   
    print("\n🎉 Proses Selesai!")
    print(f"File HTML sudah ada di folder: **{OUTPUT_DIR}/**")
    print("GitHub Actions akan melakukan commit dan push file-file ini ke repositori Anda.")
