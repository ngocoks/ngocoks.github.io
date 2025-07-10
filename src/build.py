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
ALL_BLOGGER_POSTS_CACHE_FILE = "all_blogger_posts_cache.json" # Cache semua post dari Blogger
PUBLISHED_LOG_FILE = "published_posts.json" # Log ID post yang sudah dipublikasikan

# --- Konfigurasi Gemini API ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# --- Daftar Kata yang Akan Diganti/Disensor ---
# (Pastikan ini sesuai dengan preferensi Anda)
REPLACEMENTS = {
    "kontol": "[sensor]",
    "memek": "[sensor]",
    "ngentot": "[sensor]",
    "jembut": "[sensor]",
    "titit": "[sensor]",
    "peler": "[sensor]",
    "coli": "[sensor]",
    "crot": "[sensor]",
    "kimak": "[sensor]",
    "ngocok": "[sensor]",
    "penis": "[sensor]",
    "vagina": "[sensor]",
    "seks": "[sensor]",
    "fuck": "[sensor]",
    "bitch": "[sensor]",
    "asshole": "[sensor]",
    "masturbasi": "[sensor]",
    "croott": "[sensor]"
    # Tambahkan kata lain yang ingin disensor di sini
}

# --- Fungsi Utility ---
def extract_pure_text_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    for script_or_style in soup(["script", "style"]):
        script_or_style.extract() # Hapus semua tag script dan style
    text = soup.get_text(separator=' ', strip=True)
    return text

def remove_anchor_tags_and_apply_replacements_to_html(html_content):
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
                # Gunakan regex untuk pencarian case-insensitive dan whole word
                modified_text = re.sub(r'\b' + re.escape(old) + r'\b', new, modified_text, flags=re.IGNORECASE)
            
            if modified_text != original_text:
                element.replace_with(modified_text)
                
    return str(soup)

def load_custom_css():
    if os.path.exists(CUSTOM_CSS_PATH):
        with open(CUSTOM_CSS_PATH, 'r', encoding='utf-8') as f:
            return f.read()
    print(f"⚠️ Peringatan: File CSS kustom tidak ditemukan di '{CUSTOM_CSS_PATH}'.")
    return ""

def get_post_image_url(post):
    # Mencari gambar di dalam konten
    content = post.get('content', '')
    soup = BeautifulSoup(content, 'html.parser')
    img_tag = soup.find('img')
    if img_tag and img_tag.has_attr('src'):
        return img_tag['src']
    
    # Jika tidak ada gambar di konten, coba cek thumbnail (jika ada di data API)
    if post.get('images'):
        for img in post['images']:
            if img.get('url'):
                return img['url']
                
    return None # Tidak ada gambar ditemukan

def sanitize_filename(title):
    # Mengganti karakter tidak valid dengan underscore dan membatasi panjang
    filename = re.sub(r'[^\w\-]', '_', slugify(title))
    return filename[:100] # Batasi panjang filename

def load_published_posts_state():
    if os.path.exists(PUBLISHED_LOG_FILE):
        with open(PUBLISHED_LOG_FILE, 'r', encoding='utf-8') as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                print(f"⚠️ Peringatan: File state '{PUBLISHED_LOG_FILE}' rusak. Membuat ulang.")
                return set()
    return set()

def save_published_posts_state(published_ids):
    with open(PUBLISHED_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(published_ids), f, indent=4, ensure_ascii=False)

def get_all_blogger_posts_and_preprocess(api_key, blog_id):
    all_posts = []
    next_page_token = None
    
    while True:
        url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts?key={api_key}&fetchBodies=true"
        if next_page_token:
            url += f"&pageToken={next_page_token}"
            
        print(f"Mengambil postingan dari Blogger API... {'(lanjutan)' if next_page_token else ''}")
        response = requests.get(url)
        response.raise_for_status() # Akan menimbulkan error untuk status kode HTTP yang buruk
        data = response.json()
        
        posts = data.get('items', [])
        for post in posts:
            # Tambahkan processed_title dan pure_text_content_for_gemini
            post['processed_title'] = post.get('title', 'Untitled Post')
            post['pure_text_content_for_gemini'] = extract_pure_text_from_html(post.get('content', ''))
            post['content_html_ready_for_pub'] = remove_anchor_tags_and_apply_replacements_to_html(post.get('content', ''))
            all_posts.append(post)
            
        next_page_token = data.get('nextPageToken')
        if not next_page_token:
            break
            
    print(f"✅ Berhasil mengambil {len(all_posts)} postingan dari Blogger API.")
    return all_posts

# --- Fungsi Inti: Interaksi dengan Gemini AI ---
def edit_first_300_words_with_gemini(post_id, title, pure_text_to_edit):
    if not isinstance(pure_text_to_edit, str):
        print(f"Error: pure_text_to_edit bukan string untuk post ID {post_id}.")
        return ""

    words = pure_text_to_edit.split()
    
    if len(words) < 50:
        print(f"Postingan ID {post_id} terlalu pendek ({len(words)} kata) untuk diedit Gemini. Melewatkan.")
        return "" 

    text_to_send = " ".join(words[:300])

    print(f"Mengirim 300 kata pertama dari artikel '{title}' (ID: {post_id}) ke Gemini AI untuk diedit...")

    try:
        model = genai.GenerativeModel(
            model_name='gemini-pro',
            generation_config={"temperature": 0.7, "top_p": 0.9, "top_k": 40},
            safety_settings=[
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ]
        )
        
        prompt_template = f"""
        Saya akan memberikan sebuah teks artikel. Tugas Anda adalah menyunting 300 kata pertama dari teks ini untuk menjadikannya lebih menarik, ringkas, dan optimasi SEO, tanpa mengubah makna aslinya secara signifikan. Fokus pada penggunaan kata-kata yang relevan untuk tema 'cerita dewasa 2025' dan gaya bahasa yang memikat seperti Anda (Gemini AI), namun tetap menjaga keaslian pesan dan tidak menciptakan informasi baru. Pastikan output Anda adalah teks murni, tanpa tag HTML atau Markdown.
        
        Teks artikel:
        {text_to_send}
        """
        
        response = model.generate_content(prompt_template)
        
        edited_text_from_gemini = response.text
        cleaned_edited_text = extract_pure_text_from_html(edited_text_from_gemini) 

        print(f"✅ Gemini AI selesai mengedit 300 kata pertama untuk '{title}'.")
        return cleaned_edited_text

    except Exception as e:
        print(f"⚠️ Gagal mengedit artikel '{title}' (ID: {post_id}) dengan Gemini AI: {e}")
        return ""

# --- Fungsi untuk Membangun Halaman Index dan Label (BARU/Diperbaiki) ---
def build_index_and_label_pages(all_published_posts_data, all_unique_labels_list):
    print("Membangun ulang halaman index dan label untuk SEMUA artikel yang diterbitkan...")

    # Urutkan postingan berdasarkan tanggal published terbaru
    all_published_posts_data.sort(key=lambda x: datetime.fromisoformat(x['published'].replace('Z', '+00:00')), reverse=True)

    # --- Render Halaman Index ---
    list_items_html_for_index = []
    for post in all_published_posts_data:
        post_slug = sanitize_filename(post['processed_title'])
        permalink_rel = f"/{post_slug}-{post['id']}.html"
        
        snippet_for_index = post.get('description_snippet', '')
        # Jika description_snippet tidak ada, ambil 50 kata pertama dari teks murni
        if not snippet_for_index and post.get('pure_text_content_for_gemini'):
            snippet_for_index = " ".join(post['pure_text_content_for_gemini'].split()[:50]) + "..."
        
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
        # Urutkan berdasarkan tanggal published terbaru
        posts_for_this_label.sort(key=lambda x: datetime.fromisoformat(x['published'].replace('Z', '+00:00')), reverse=True)

        list_items_html_label = []
        for post in posts_for_this_label:
            post_slug = sanitize_filename(post['processed_title'])
            permalink_rel = f"/{post_slug}-{post['id']}.html"

            snippet_for_label = post.get('description_snippet', '')
            if not snippet_for_label and post.get('pure_text_content_for_gemini'):
                snippet_for_label = " ".join(post['pure_text_content_for_gemini'].split()[:50]) + "..."
            
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
    post_slug = sanitize_filename(post['processed_title'])
    output_filename = f"{post_slug}-{post['id']}.html"
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    permalink_rel = f"/{output_filename}"
    permalink_abs = f"{BASE_SITE_URL}{permalink_rel}"
    
    edited_first_300_words_pure_text = post.get('processed_content_with_gemini', '')
    full_original_pure_text = post.get('pure_text_content_for_gemini', '')
    
    final_pure_text_for_article = ""

    if edited_first_300_words_pure_text:
        print("Menggabungkan 300 kata hasil editan Gemini dengan sisa artikel asli.")
        original_words_list = full_original_pure_text.split()
        
        if len(original_words_list) >= 300:
            remaining_original_pure_text = " ".join(original_words_list[300:])
            final_pure_text_for_article = edited_first_300_words_pure_text + "\n\n" + remaining_original_pure_text
        else:
            final_pure_text_for_article = edited_first_300_words_pure_text if edited_first_300_words_pure_text else full_original_pure_text
            print("Artikel kurang dari 300 kata, menggunakan hasil editan Gemini (jika ada) atau teks asli.")
    else:
        print("Gemini AI tidak mengedit. Menggunakan teks murni asli artikel.")
        final_pure_text_for_article = full_original_pure_text

    final_article_content_html = ""
    for paragraph in final_pure_text_for_article.split('\n\n'):
        if paragraph.strip():
            formatted_paragraph = paragraph.replace('\n', '<br>') 
            final_article_content_html += f"<p>{formatted_paragraph}</p>\n"

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
    # 1. Pastikan folder output bersih
    print(f"Membersihkan folder output: {OUTPUT_DIR}/")
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Salin logo ke folder dist
    if os.path.exists(LOGO_PATH):
        shutil.copy(LOGO_PATH, os.path.join(OUTPUT_DIR, "logo.png"))
        print(f"✅ Logo '{os.path.basename(LOGO_PATH)}' disalin ke '{OUTPUT_DIR}/'.")
    else:
        print(f"⚠️ Peringatan: Logo tidak ditemukan di '{LOGO_PATH}'. Pastikan Anda menempatkannya di sana.")

    # 2. Muat atau ambil semua postingan dari Blogger API
    if os.path.exists(ALL_BLOGGER_POSTS_CACHE_FILE):
        print(f"Memuat semua postingan dari cache '{ALL_BLOGGER_POSTS_CACHE_FILE}'.")
        with open(ALL_BLOGGER_POSTS_CACHE_FILE, 'r', encoding='utf-8') as f:
            all_posts_preprocessed = json.load(f)
    else:
        print(f"Cache '{ALL_BLOGGER_POSTS_CACHE_FILE}' tidak ditemukan. Mengambil semua postingan dari Blogger API...")
        all_posts_preprocessed = get_all_blogger_posts_and_preprocess(API_KEY, BLOG_ID)
        with open(ALL_BLOGGER_POSTS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_posts_preprocessed, f, indent=4, ensure_ascii=False)
        print(f"✅ Semua postingan disimpan ke cache '{ALL_BLOGGER_POSTS_CACHE_FILE}'.")

    # 3. Muat state postingan yang sudah diterbitkan
    published_ids = load_published_posts_state()

    # 4. Filter postingan yang belum diterbitkan dan siapkan untuk Gemini
    unpublished_posts = []
    all_unique_labels_across_all_posts = set()

    for post in all_posts_preprocessed:
        post_id_str = str(post['id'])
        # Kumpulkan semua label unik dari semua postingan (termasuk yang sudah diterbitkan dan belum)
        if post.get('labels'):
            for label in post['labels']:
                all_unique_labels_across_all_posts.add(label)

        if post_id_str not in published_ids:
            # Pastikan post['pure_text_content_for_gemini'] dan post['content_html_ready_for_pub']
            # sudah ada di sini, ini seharusnya sudah dibuat di get_all_blogger_posts_and_preprocess.
            # Jika ada kemungkinan data tidak lengkap, bisa tambahkan fallback di sini.
            unpublished_posts.append(post)
            
    if not unpublished_posts:
        print("Tidak ada artikel baru yang perlu diterbitkan hari ini.")
        # Jika tidak ada artikel baru, kita tetap perlu membangun ulang index/label
        # untuk memastikan semua artikel yang sudah ada tampil.
        if all_posts_preprocessed:
            all_published_posts_data = [p for p in all_posts_preprocessed if str(p['id']) in published_ids]
            build_index_and_label_pages(all_published_posts_data, list(all_unique_labels_across_all_posts))
        
        print("🎉 Proses Selesai! (Tidak ada artikel baru yang diterbitkan)")
        print(f"File HTML sudah ada di folder: **{OUTPUT_DIR}/**")
        exit()

    # Urutkan postingan yang belum diterbitkan berdasarkan tanggal publish (terbaru lebih dulu)
    unpublished_posts.sort(key=lambda x: datetime.fromisoformat(x['published'].replace('Z', '+00:00')), reverse=True)

    # 5. Pilih satu postingan untuk diterbitkan hari ini (yang paling baru dari yang belum diterbitkan)
    post_to_publish = unpublished_posts[0]
   
    print(f"🌟 Menerbitkan artikel berikutnya: '{post_to_publish.get('processed_title')}' (ID: {post_to_publish.get('id')})\n")
   
    # Lakukan pengeditan AI pada teks murni yang disiapkan untuk Gemini
    edited_pure_text_from_gemini_300_words = edit_first_300_words_with_gemini(
        post_to_publish['id'],
        post_to_publish['processed_title'],
        post_to_publish['pure_text_content_for_gemini']
    )
    
    # Simpan hasil editan Gemini (HANYA 300 KATA) ke dalam post_to_publish
    post_to_publish['processed_content_with_gemini'] = edited_pure_text_from_gemini_300_words

    # 6. Hasilkan file HTML untuk postingan yang dipilih (individual)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    build_single_post_page(post_to_publish) # Membuat file HTML untuk artikel individu ini

    # 7. Tambahkan ID postingan ke daftar yang sudah diterbitkan dan simpan state
    published_ids.add(str(post_to_publish['id']))
    save_published_posts_state(published_ids)
    print(f"✅ State file '{PUBLISHED_LOG_FILE}' diperbarui.")
    
    # 8. Setelah satu artikel diterbitkan dan statusnya diperbarui,
    # bangun ulang halaman index dan label dengan SEMUA artikel yang sudah diterbitkan.
    # Muat ulang all_posts_preprocessed jika ada perubahan signifikan yang perlu dipantau,
    # atau cukup filter dari data yang sudah ada jika post_to_publish sudah ada di dalamnya.
    
    # Untuk memastikan data paling up-to-date, kita bisa muat ulang atau pastikan post_to_publish
    # ditambahkan ke all_posts_preprocessed sebelum memfilter.
    # Asumsi: all_posts_preprocessed di awal sudah berisi semua data dari Blogger.
    # kita hanya perlu memastikan 'published_ids' sudah diperbarui.

    # Dapatkan daftar semua postingan yang sekarang sudah diterbitkan
    all_published_posts_data = [p for p in all_posts_preprocessed if str(p['id']) in published_ids]
    
    # Bangun halaman index dan label dengan semua artikel yang sudah diterbitkan
    build_index_and_label_pages(all_published_posts_data, list(all_unique_labels_across_all_posts))
   
    print("\n🎉 Proses Selesai!")
    print(f"File HTML sudah ada di folder: **{OUTPUT_DIR}/**")
    print("GitHub Actions akan melakukan commit dan push file-file ini ke repositori Anda.")
