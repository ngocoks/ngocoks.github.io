import requests
import json
import os
import shutil # Import shutil for file copying
from bs4 import BeautifulSoup
from slugify import slugify
from datetime import datetime

# --- KONFIGURASI PENTING ---
API_KEY = os.getenv("BLOGGER_API_KEY")
BLOG_ID = os.getenv("BLOGGER_BLOG_ID")

OUTPUT_DIR = "dist" # Output situs statis yang akan di-deploy ke GitHub Pages

# URL dasar situs Anda di GitHub Pages. GANTI INI DENGAN URL REPO ANDA!
# Contoh: Jika username Anda 'ngocoks' dan nama repo 'blogger-static', maka https://ngocoks.github.io/blogger-static
# Jika Anda menggunakan custom domain atau ngocoks.github.io (tanpa nama repo), pastikan sesuai.
BASE_SITE_URL = "https://ngocoks.github.io" # <<< GANTI INI DENGAN DOMAIN/SUBDOMAIN GITHUB PAGES ANDA!
BLOG_NAME = "Cerita Dewasa 2025" # <<< GANTI DENGAN NAMA BLOG ANDA

# Path ke file CSS dan logo (akan di-inline atau disalin)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
CUSTOM_CSS_PATH = os.path.join(STATIC_DIR, "style.css")
LOGO_PATH = os.path.join(STATIC_DIR, "logo.png") # Pastikan logo.png ada di folder static

# Pastikan direktori output ada
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- FUNGSI BANTUAN ---

def get_snippet(html_content, word_limit=30): # Mengurangi word_limit untuk snippet yang lebih ringkas
    """Mengekstrak snippet teks bersih dari konten HTML."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')
    text = soup.get_text(separator=' ', strip=True) # strip=True untuk membersihkan spasi ekstra
    words = text.split()
    return ' '.join(words[:word_limit]) + ('...' if len(words) > word_limit else '')

### PERUBAHAN BARU DI SINI ###
def truncate_html_for_accordion(html_content, chars_to_display=7000):
    """
    Memotong konten HTML pada jumlah karakter tertentu secara 'aman'
    dan mengembalikannya sebagai dua bagian: terlihat dan tersembunyi.
    Fungsi ini mirip dengan logika JavaScript Anda.
    """
    if not html_content:
        return "", ""

    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Elemen-elemen yang akan dianggap sebagai "self-closing" di konteks pemotongan
    # Ini membantu mencegah tag seperti <img> atau <br> memotong struktur
    self_closing_tags = ['img', 'br', 'hr', 'input', 'link', 'meta', 'area', 'base', 'col', 'embed', 'keygen', 'param', 'source', 'track', 'wbr']

    current_length = 0
    visible_elements = []
    hidden_elements = []
    
    # Untuk melacak tag yang terbuka
    open_tags_stack = []

    # Iterasi melalui konten elemen-per-elemen
    for child in soup.contents:
        child_html = str(child)
        child_text = child.get_text(strip=True) # Hanya teks terlihat
        
        # Jika elemen adalah tag
        if hasattr(child, 'name') and child.name:
            tag_name = child.name.lower()
            if child_text: # Jika ada teks, hitung panjangnya
                # Coba tentukan apakah elemen ini akan membuat kita melewati batas
                if current_length + len(child_text) <= chars_to_display:
                    visible_elements.append(child)
                    current_length += len(child_text)
                    if tag_name not in self_closing_tags:
                        open_tags_stack.append(tag_name) # Simpan tag pembuka
                else:
                    # Elemen ini melebihi batas, perlu dipotong
                    remaining_chars = chars_to_display - current_length
                    
                    if remaining_chars > 0:
                        # Coba potong konten teks di dalam elemen ini
                        # Ini adalah bagian yang paling kompleks dan mungkin tidak sempurna
                        # untuk semua skenario HTML yang rumit.
                        temp_soup_child = BeautifulSoup(child_html, 'html.parser')
                        for string in temp_soup_child.strings:
                            if remaining_chars <= 0:
                                break
                            
                            original_string = str(string)
                            string_len = len(original_string)
                            
                            if string_len > remaining_chars:
                                string.replace_with(original_string[:remaining_chars])
                                remaining_chars = 0
                            else:
                                remaining_chars -= string_len
                        
                        visible_elements.append(temp_soup_child)
                        current_length = chars_to_display # Batas tercapai
                    
                    # Tambahkan sisa konten ke bagian tersembunyi
                    hidden_elements.append(BeautifulSoup(html_content[html_content.find(child_html):], 'html.parser'))
                    break # Berhenti memproses elemen terlihat
            else: # Elemen tanpa teks (misalnya <img>, <br>)
                if current_length <= chars_to_display: # Asumsi elemen kosong tidak dihitung karakter tapi harus tetap di bagian visible
                    visible_elements.append(child)
        else: # Ini adalah String (teks langsung di root, bukan dalam tag)
            if current_length + len(child_text) <= chars_to_display:
                visible_elements.append(child)
                current_length += len(child_text)
            else:
                visible_elements.append(str(child)[:chars_to_display - current_length])
                current_length = chars_to_display
                # Tambahkan sisa teks ini dan elemen berikutnya ke hidden
                hidden_elements.append(BeautifulSoup(html_content[html_content.find(child_html):], 'html.parser'))
                break

    # Gabungkan elemen yang terlihat
    visible_html_soup = BeautifulSoup('', 'html.parser')
    for el in visible_elements:
        visible_html_soup.append(el)
        
    # Perbaiki tag yang tidak tertutup di bagian terlihat
    # Ini memerlukan logic yang lebih dalam daripada hanya stack.
    # Cara paling aman adalah memastikan parser BeautifulSoup menangani penutupan tag saat string di-re-parse.
    # Untuk saat ini, kita mengandalkan BeautifulSoup untuk re-rendering valid.
    
    # Gabungkan elemen yang tersembunyi
    hidden_html_soup = BeautifulSoup('', 'html.parser')
    # Jika kita sudah pecah dari loop karena batas tercapai, hidden_elements sudah berisi sisa
    if not hidden_elements: # Jika belum ada elemen tersembunyi, ambil sisanya dari soup asli
        full_html_str = str(soup)
        visible_html_str_temp = str(visible_html_soup)
        
        # Temukan indeks di mana bagian terlihat berakhir di HTML asli
        # Ini adalah cara sederhana, mungkin tidak sempurna untuk semua kasus
        idx = full_html_str.find(visible_html_str_temp)
        if idx != -1:
            end_idx = idx + len(visible_html_str_temp)
            if end_idx < len(full_html_str):
                hidden_html_soup = BeautifulSoup(full_html_str[end_idx:], 'html.parser')


    # Kembali string HTML yang bersih
    return str(visible_html_soup), str(hidden_html_soup)


def convert_to_amp(html_content):
    """
    Mengonversi HTML biasa ke HTML yang kompatibel dengan AMP dan menambahkan amp-accordion
    untuk fitur "detail otomatis".
    """
    if not html_content:
        return ""
        
    # --- Potong Konten untuk amp-accordion ---
    # Definisikan batas karakter untuk konten yang terlihat
    # Sesuaikan angka ini sesuai kebutuhan Anda
    chars_for_summary = 7000 
    
    visible_html, hidden_html = truncate_html_for_accordion(html_content, chars_to_display=chars_for_summary)

    soup = BeautifulSoup(visible_html, 'html.parser') # Awalnya, proses hanya bagian yang terlihat

    # Ubah img menjadi amp-img
    for img in soup.find_all('img'):
        amp_img = soup.new_tag('amp-img')
        for attr, value in img.attrs.items():
            if attr in ['src', 'alt']:
                amp_img[attr] = value
            # Pastikan width/height adalah angka dan salin jika ada
            elif attr == 'width' and str(value).isdigit():
                amp_img[attr] = value
            elif attr == 'height' and str(value).isdigit():
                amp_img[attr] = value
        
        # Berikan width/height default jika tidak ada, penting untuk layout AMP
        if 'width' not in amp_img.attrs: amp_img['width'] = '600'
        if 'height' not in amp_img.attrs: amp_img['height'] = '400'
        
        amp_img['layout'] = 'responsive' # Layout paling umum dan adaptif
        
        img.replace_with(amp_img)

    # Hapus atribut style inline
    for tag in soup.find_all(attrs={'style': True}):
        del tag['style']

    # Hapus script tag (kecuali type="application/ld+json")
    for script_tag in soup.find_all('script'):
        if 'type' in script_tag.attrs and script_tag['type'] == 'application/ld+json':
            continue # Biarkan script JSON-LD
        script_tag.decompose()
        
    # Hapus atribut 'id' dari elemen non-AMP untuk mencegah konflik/validasi AMP
    for tag in soup.find_all(True):
        if 'id' in tag.attrs and not tag.name.startswith('amp-'):
            del tag['id']
            
    # Hapus elemen yang tidak valid di AMP (misal: iframes, form, input, kecuali dari whitelist)
    invalid_tags = ['iframe', 'form', 'input', 'video', 'audio', 'object', 'embed']
    for tag_name in invalid_tags:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Gabungkan HTML yang sudah dibersihkan dengan bagian tersembunyi dalam amp-accordion
    # Hanya tambahkan accordion jika memang ada konten tersembunyi
    final_amp_html = str(soup)
    
    if hidden_html.strip(): # Pastikan ada konten tersembunyi
        # Proses hidden_html juga untuk AMP compliance (amp-img, hapus script, dll.)
        hidden_soup = BeautifulSoup(hidden_html, 'html.parser')
        
        for img in hidden_soup.find_all('img'):
            amp_img = hidden_soup.new_tag('amp-img')
            for attr, value in img.attrs.items():
                if attr in ['src', 'alt']:
                    amp_img[attr] = value
                elif attr == 'width' and str(value).isdigit():
                    amp_img[attr] = value
                elif attr == 'height' and str(value).isdigit():
                    amp_img[attr] = value
            if 'width' not in amp_img.attrs: amp_img['width'] = '600'
            if 'height' not in amp_img.attrs: amp_img['height'] = '400'
            amp_img['layout'] = 'responsive'
            img.replace_with(amp_img)

        for tag in hidden_soup.find_all(attrs={'style': True}):
            del tag['style']
        for script_tag in hidden_soup.find_all('script'):
            if 'type' in script_tag.attrs and script_tag['type'] == 'application/ld+json':
                continue
            script_tag.decompose()
        for tag in hidden_soup.find_all(True):
            if 'id' in tag.attrs and not tag.name.startswith('amp-'):
                del tag['id']
        for tag_name in invalid_tags:
            for tag in hidden_soup.find_all(tag_name):
                tag.decompose()
        
        processed_hidden_html = str(hidden_soup)

        # Buat elemen amp-accordion
        accordion_html = f"""
<amp-accordion animate>
  <section>
    <h3>Baca Selanjutnya</h3>
    <div>
      {processed_hidden_html}
    </div>
  </section>
</amp-accordion>
"""
        final_amp_html += accordion_html

    # Membersihkan entitas HTML ganda yang mungkin muncul dari Beautiful Soup
    # Ini mungkin tidak diperlukan jika soup sudah menangani encoding dengan benar
    # cleaned_html = final_amp_html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
    return final_amp_html

### AKHIR PERUBAHAN BARU ###

def generate_breadcrumbs_data(post_title, post_labels, base_url):
    """Menghasilkan struktur breadcrumbs untuk JSON-LD."""
    breadcrumbs = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": base_url}
    ]
    
    if post_labels:
        main_label = post_labels[0] # Ambil label pertama sebagai kategori utama
        breadcrumbs.append({
            "@type": "ListItem",
            "position": 2,
            "name": main_label,
            "item": f"{base_url}/{slugify(main_label)}.html"
        })
        breadcrumbs.append({
            "@type": "ListItem",
            "position": 3,
            "name": post_title,
            "item": "" # URL akan disisipkan di template untuk item terakhir
        })
    else:
        breadcrumbs.append({
            "@type": "ListItem",
            "position": 2,
            "name": post_title,
            "item": ""
        })
    return breadcrumbs

def get_post_image_url(post_data):
    """Mengekstrak URL gambar utama dari data postingan."""
    if 'images' in post_data and post_data['images']:
        return post_data['images'][0]['url']
        
    # Fallback: coba ekstrak dari konten jika tidak ada di 'images' API field
    soup = BeautifulSoup(post_data.get('content', ''), 'html.parser')
    first_img = soup.find('img')
    if first_img and 'src' in first_img.attrs:
        return first_img['src']
    return "" # Mengembalikan string kosong jika tidak ditemukan gambar

def get_blogger_data(api_key, blog_id):
    """Mengambil semua postingan dari Blogger API."""
    all_posts = []
    next_page_token = None
    
    print("Mengambil data dari Blogger API...")

    while True:
        url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts"
        params = {
            "key": api_key,
            "fetchImages": True,
            "maxResults": 500, # Max per request
            "fields": "items(id,title,url,published,updated,content,labels,images,author(displayName),replies(totalItems)),nextPageToken" # Ditambahkan replies(totalItems) untuk data komentar, meskipun tidak digunakan di tampilan
        }
        if next_page_token:
            params["pageToken"] = next_page_token

        try:
            response = requests.get(url, params=params)
            response.raise_for_status() # Akan memicu HTTPError untuk status kode 4xx/5xx
            data = response.json()
            
            posts_batch = data.get("items", [])
            all_posts.extend(posts_batch)
            print(f"  > Mengambil {len(posts_batch)} postingan. Total: {len(all_posts)}")

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break # Tidak ada halaman lagi

        except requests.exceptions.HTTPError as e:
            print(f"Error HTTP: {e.response.status_code} - {e.response.text}")
            return None # Kembalikan None untuk mengindikasikan kegagalan
        except requests.exceptions.RequestException as e:
            print(f"Error jaringan atau request: {e}")
            return None
    
    print(f"Total {len(all_posts)} postingan berhasil diambil.")
    return all_posts

# --- Fungsi untuk Membangun Bagian HTML ---

def build_head_content(page_title, canonical_url, custom_css_content):
    """Membangun bagian <head> dari dokumen HTML."""
    head_html = f"""
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, minimum-scale=1">
    <link rel="canonical" href="{canonical_url}">
    <title>{page_title}</title>
    <meta name="google-site-verification" content="wxkvpqMwTAGfQ5E0xjycz-q-Elshg4pLh8B_7JhzgGk" />

    <style amp-boilerplate>body{{-webkit-animation:-amp-start 8s steps(1,end) 0s 1 normal both;-moz-animation:-amp-start 8s steps(1,end) 0s 1 normal both;-ms-animation:-amp-start 8s steps(1,end) 0s 1 normal both;animation:-amp-start 8s steps(1,end) 0s 1 normal both}}@-webkit-keyframes -amp-start{{from{{visibility:hidden}}to{{visibility:visible}}}}@-moz-keyframes -amp-start{{from{{visibility:hidden}}to{{visibility:visible}}}}@-ms-keyframes -amp-start{{from{{visibility:hidden}}to{{visibility:visible}}}}@-o-keyframes -amp-start{{from{{visibility:hidden}}to{{visibility:visible}}}}@keyframes -amp-start{{from{{visibility:hidden}}to{{visibility:visible}}}}</style><noscript><style amp-boilerplate>body{{-webkit-animation:none;-moz-animation:none;-ms-animation:none;animation:none}}</style></noscript>
    <script async src="https://cdn.ampproject.org/v0.js"></script>

    <script async custom-element="amp-sidebar" src="https://cdn.ampproject.org/v0/amp-sidebar-0.1.js"></script>
    <script async custom-element="amp-carousel" src="https://cdn.ampproject.org/v0/amp-carousel-0.1.js"></script>
    ### PERUBAHAN BARU DI SINI ###
    <script async custom-element="amp-accordion" src="https://cdn.ampproject.org/v0/amp-accordion-0.1.js"></script>
    ### AKHIR PERUBAHAN BARU ###

    <style amp-custom>
        {custom_css_content}
        /* Gaya tambahan untuk amp-accordion (bisa dimasukkan ke style.css juga) */
        amp-accordion section {
            border: 1px solid #ddd;
            margin-top: 15px; /* Beri sedikit ruang dari konten utama */
            border-radius: 4px;
            overflow: hidden; /* Pastikan sudut membulat diterapkan */
        }
        amp-accordion section > h3 { /* Gunakan h3 karena ini header internal accordion */
            background-color: #007bff;
            color: white;
            padding: 15px;
            margin: 0;
            font-size: 1.1em;
            cursor: pointer;
            border-bottom: 1px solid #0056b3;
            transition: background-color 0.3s ease;
        }
        amp-accordion section > h3:hover {
            background-color: #0056b3;
        }
        amp-accordion section[expanded] > h3 {
            /* Gaya saat terbuka, misalnya tidak ada border bawah */
            border-bottom: none;
        }
        amp-accordion section > div {
            padding: 15px;
            background-color: #f9f9f9;
        }
    </style>
    """
    return head_html

def build_header_and_sidebar(all_labels, current_blog_name):
    """Membangun bagian header dan sidebar navigasi."""
    logo_tag = ""
    if os.path.exists(LOGO_PATH):
        # Perhatikan: PATH LOGO DI SINI HARUS ABSOLUT UNTUK GITHUB PAGES
        # Pastikan logo.png ada di root direktori 'dist'
        logo_tag = f'<amp-img src="{BASE_SITE_URL}/logo.png" width="80" height="40" layout="fixed" alt="Logo Blog"></amp-img>'


    header_html = f"""
    <header class="header">
        <button on="tap:sidebar-menu.toggle" class="hamburger" aria-label="Open navigation">☰</button>
        <h1><a href="/">{logo_tag} {current_blog_name}</a></h1>
        <div class="search-icon">
            </div>
    </header>

    <amp-sidebar id="sidebar-menu" layout="nodisplay" side="left">
        <button on="tap:sidebar-menu.toggle" class="close-button" aria-label="Close navigation">✕</button>
        <ul>
            <li><a href="/">Beranda</a></li>
            {"".join([f'<li><a href="/{slugify(label)}.html">{label}</a></li>' for label in all_labels])}
        </ul>
    </amp-sidebar>
    """
    return header_html

def build_footer(current_blog_name, base_site_url):
    """Membangun bagian footer."""
    footer_html = f"""
    <footer>
        <div class="container">
            <p>&copy; {datetime.now().year} {current_blog_name}. All rights reserved.</p>
            
        </div>
    </footer>
    """
    return footer_html

def build_html_document(head_content, body_content):
    """Membangun struktur dasar dokumen HTML AMP."""
    return f"""
<!doctype html>
<html ⚡ lang="en">
<head>
    {head_content}
</head>
<body>
    {body_content}
</body>
</html>
"""

def build_site(posts):
    print("Memulai proses pembangunan situs...")
    
    if not posts:
        print("Tidak ada postingan untuk dibangun. Menghentikan.")
        return

    # Baca Custom CSS satu kali
    try:
        with open(CUSTOM_CSS_PATH, 'r', encoding='utf-8') as f:
            custom_css_content = f.read()
    except FileNotFoundError:
        print(f"Peringatan: File CSS '{CUSTOM_CSS_PATH}' tidak ditemukan. Menggunakan CSS kosong.")
        custom_css_content = ""

    # Salin logo ke direktori output jika ada
    if os.path.exists(LOGO_PATH):
        shutil.copy(LOGO_PATH, os.path.join(OUTPUT_DIR, os.path.basename(LOGO_PATH)))
        print(f"Logo '{os.path.basename(LOGO_PATH)}' disalin ke '{OUTPUT_DIR}'.")
    
    # Kumpulkan semua label unik
    all_unique_labels = set()
    for post in posts:
        if 'labels' in post:
            for label in post['labels']:
                all_unique_labels.add(label)
    
    unique_labels_list = sorted(list(all_unique_labels))
    print(f"Ditemukan {len(unique_labels_list)} label unik.")

    # Urutkan postingan berdasarkan tanggal publikasi terbaru
    sorted_posts = sorted(posts, key=lambda p: p['published'], reverse=True)
    
    # Bagian header dan sidebar (sama untuk semua halaman)
    global_header_sidebar_html = build_header_and_sidebar(unique_labels_list, BLOG_NAME)
    global_footer_html = build_footer(BLOG_NAME, BASE_SITE_URL)

    # --- Render Halaman Index (dengan Paginasi) ---
    print("Membangun halaman index...")
    
    posts_per_page = 10
    total_posts = len(sorted_posts)
    total_pages = (total_posts + posts_per_page - 1) // posts_per_page
    
    for page_num in range(1, total_pages + 1):
        start_idx = (page_num - 1) * posts_per_page
        end_idx = start_idx + posts_per_page
        paginated_posts = sorted_posts[start_idx:end_idx]

        list_items_html = []
        for p in paginated_posts:
            # Ambil label pertama sebagai "kategori" utama untuk tampilan
            category_html = ""
            if p.get('labels'):
                category_html = f'<span class="category">{p["labels"][0]}</span>'
            
            snippet = get_snippet(p.get('content', ''))
            thumbnail_url = get_post_image_url(p)
            post_slug = slugify(p['title'])
            permalink = f"/{post_slug}-{p['id']}.html"
            published_date_formatted = datetime.strptime(p['published'].split('T')[0], '%Y-%m-%d').strftime('%d %b, %Y')
            
            thumbnail_tag = ""
            if thumbnail_url:
                thumbnail_tag = f"""
                <div class="post-thumbnail">
                    <amp-img src="{thumbnail_url}" width="100" height="75" layout="responsive" alt="{p['title']}"></amp-img>
                </div>
                """

            list_items_html.append(f"""
            <div class="post-item">
                {thumbnail_tag}
                <div class="post-content">
                    <div class="post-meta">
                        {category_html}
                        </div>
                    <h2><a href="{permalink}">{p['title']}</a></h2>
                    <p>{snippet}</p>
                    <p><small>By {p['author']['displayName']} - {published_date_formatted}</small></p>
                </div>
            </div>
            """)
            
        # Navigasi paginasi
        pagination_html = "<div class='pagination'>"
        if page_num > 1:
            prev_page_link = "/index.html" if page_num == 2 else f"/index_p{page_num-1}.html"
            pagination_html += f"<a href='{prev_page_link}'>Sebelumnya</a>"
        pagination_html += f"<span class='current-page'>{page_num}</span>"
        if page_num < total_pages:
            next_page_link = f"/index_p{page_num+1}.html"
            pagination_html += f"<a href='{next_page_link}'>Selanjutnya</a>"
        pagination_html += "</div>"

        # Tentukan permalink halaman index saat ini untuk canonical
        current_index_permalink_rel = "/index.html" if page_num == 1 else f"/index_p{page_num}.html"
        current_index_permalink_abs = f"{BASE_SITE_URL}{current_index_permalink_rel}"

        # Tambahkan ruang iklan di sini
        ad_banner_space_html = """
        <div class="ad-banner-space">
            Space Iklan Banner
        </div>
        """

        # Bangun konten body untuk halaman index
        index_body_content = f"""
        {global_header_sidebar_html}
        <main class="container">
            <h1 class="page-title">Terbaru</h1>
            <div class="post-list">
                {''.join(list_items_html)}
            </div>
            {pagination_html}
            {ad_banner_space_html}
        </main>
        {global_footer_html}
        """

        # Bangun head untuk halaman index
        index_head_html = build_head_content(
            page_title=f"{BLOG_NAME} - Halaman {page_num}",
            canonical_url=current_index_permalink_abs,
            custom_css_content=custom_css_content
        )

        # Bangun dokumen HTML lengkap
        full_index_html = build_html_document(index_head_html, index_body_content)
        
        output_filename = "index.html" if page_num == 1 else f"index_p{page_num}.html"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_index_html)
        print(f"  > Index Page {page_num}/{total_pages} selesai: {output_filename}")

    # --- Render Halaman Artikel Individual ---
    print("Membangun halaman artikel...")
    for post in posts:
        post_slug = slugify(post['title'])
        permalink_rel = f"/{post_slug}-{post['id']}.html"
        permalink_abs = f"{BASE_SITE_URL}{permalink_rel}"
        
        # ### PERUBAHAN BARU DI SINI: convert_to_amp sekarang sudah menyertakan accordion ###
        amp_content = convert_to_amp(post.get('content', ''))
        ### AKHIR PERUBAHAN BARU ###

        main_image_url = get_post_image_url(post)
        
        # Escape string untuk JSON-LD
        escaped_title = json.dumps(post['title'])[1:-1]
        escaped_snippet = json.dumps(get_snippet(post.get('content', '')))[1:-1]
        escaped_author_name = json.dumps(post['author']['displayName'])[1:-1]
        escaped_blog_name = json.dumps(BLOG_NAME)[1:-1]
        
        # Related Posts (Ambil 3 postingan lain dari label yang sama, jika ada)
        related_posts_html = ""
        related_posts = []
        post_labels = post.get('labels', [])
        if post_labels:
            for label in post_labels:
                for p_related in sorted_posts:
                    if p_related['id'] != post['id'] and \
                       'labels' in p_related and label in p_related['labels']:
                        if len(related_posts) < 3 and p_related not in related_posts:
                            p_related_slug = slugify(p_related['title'])
                            p_related['permalink'] = f"/{p_related_slug}-{p_related['id']}.html"
                            p_related['thumbnail_url'] = get_post_image_url(p_related)
                            related_posts.append(p_related)
                        if len(related_posts) >= 3:
                            break
                if len(related_posts) >= 3:
                    break
        
        if related_posts:
            related_items_html = []
            for rp in related_posts:
                rp_thumbnail_tag = ""
                if rp['thumbnail_url']:
                    rp_thumbnail_tag = f"""
                    <div class="related-thumbnail">
                        <amp-img src="{rp['thumbnail_url']}" width="80" height="60" layout="responsive" alt="{rp['title']}"></amp-img>
                    </div>
                    """
                related_items_html.append(f"""
                <div class="related-item">
                    {rp_thumbnail_tag}
                    <h4><a href="{rp['permalink']}">{rp['title']}</a></h4>
                </div>
                """)
            related_posts_html = f"""
            <section class="related-posts">
                <h3>Postingan Terkait</h3>
                <div class="related-posts-list">
                    {''.join(related_items_html)}
                </div>
            </section>
            """

        # Breadcrumbs data untuk JSON-LD
        breadcrumbs_data = generate_breadcrumbs_data(post['title'], post_labels, BASE_SITE_URL)
        breadcrumbs_json = json.dumps(breadcrumbs_data)

        # HTML untuk Breadcrumbs di halaman
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
            else: # Item terakhir (artikel saat ini) tidak memiliki link
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

        # HTML untuk labels di bawah artikel
        labels_html = ""
        if post_labels:
            labels_links = [f'<a href="/{slugify(label)}.html">{label}</a>' for label in post_labels]
            labels_html = f"<br>Labels: {', '.join(labels_links)}"

        # JSON-LD untuk artikel
        json_ld_script = f"""
        <script type="application/ld+json">
        {{
          "@context": "https://schema.org",
          "@type": "BlogPosting",
          "headline": "{escaped_title}",
          "image": "{main_image_url}",
          "url": "{permalink_abs}",
          "datePublished": "{post['published']}",
          "dateModified": "{post['updated']}",
          "author": {{
            "@type": "Person",
            "name": "{escaped_author_name}"
          }},
          "publisher": {{
            "@type": "Organization",
            "name": "{escaped_blog_name}",
            "logo": {{
              "@type": "ImageObject",
              "url": "{BASE_SITE_URL}/logo.png"
            }}
          }},
          "description": "{escaped_snippet}"
          // "articleBody": "{json.dumps(amp_content).replace('\\n', ' ').replace('\\r', '')[1:-1]}" // articleBody cenderung terlalu besar untuk JSON-LD, jadi dihapus agar lebih ringkas
        }}
        </script>
        """

        # Bangun konten body untuk halaman artikel
        post_body_content = f"""
        {global_header_sidebar_html}
        <main class="container">
            {breadcrumbs_nav_html}
            {json_ld_script}
            <article class="article-detail">
                <header class="article-header">
                    <h1>{post['title']}</h1>
                    <p class="article-meta">
                        Dipublikasikan pada: {datetime.strptime(post['published'].split('T')[0], '%Y-%m-%d').strftime('%Y-%m-%d')} oleh {post['author']['displayName']}
                        {labels_html}
                    </p>
                </header>
                <div class="article-content">
                    {amp_content}
                </div>
            </article>
            {related_posts_html}
        </main>
        {global_footer_html}
        """
        
        # Bangun head untuk halaman artikel
        post_head_html = build_head_content(
            page_title=f"{post['title']} - {BLOG_NAME}",
            canonical_url=permalink_abs,
            custom_css_content=custom_css_content
        )

        # Bangun dokumen HTML lengkap
        full_post_html = build_html_document(post_head_html, post_body_content)
        
        output_path = os.path.join(OUTPUT_DIR, permalink_rel.lstrip('/'))
        # Pastikan direktori untuk permalink ada (misal: /kategori/artikel.html)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_post_html)
        print(f"  > Artikel selesai: {permalink_rel}")

    # --- Render Halaman Label ---
    print("Membangun halaman label...")
    for label_name in unique_labels_list:
        label_slug = slugify(label_name)
        permalink_rel = f"/{label_slug}.html"
        permalink_abs = f"{BASE_SITE_URL}{permalink_rel}"
        
        # Filter postingan untuk label ini
        posts_for_label = [
            p for p in sorted_posts if 'labels' in p and label_name in p['labels']
        ]
        
        list_items_html = []
        for p in posts_for_label:
            # Ambil label pertama sebagai "kategori" utama untuk tampilan
            category_html = ""
            if p.get('labels'):
                category_html = f'<span class="category">{p["labels"][0]}</span>'
            
            snippet = get_snippet(p.get('content', ''))
            thumbnail_url = get_post_image_url(p)
            post_slug = slugify(p['title'])
            post_item_permalink = f"/{post_slug}-{p['id']}.html"
            published_date_formatted = datetime.strptime(p['published'].split('T')[0], '%Y-%m-%d').strftime('%d %b, %Y')
            
            thumbnail_tag = ""
            if thumbnail_url:
                thumbnail_tag = f"""
                <div class="post-thumbnail">
                    <amp-img src="{thumbnail_url}" width="100" height="75" layout="responsive" alt="{p['title']}"></amp-img>
                </div>
                """

            list_items_html.append(f"""
            <div class="post-item">
                {thumbnail_tag}
                <div class="post-content">
                    <div class="post-meta">
                        {category_html}
                        </div>
                    <h2><a href="{post_item_permalink}">{p['title']}</a></h2>
                    <p>{snippet}</p>
                    <p><small>By {p['author']['displayName']} - {published_date_formatted}</small></p>
                </div>
            </div>
            """)

        # Bangun konten body untuk halaman label
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

        # Bangun head untuk halaman label
        label_head_html = build_head_content(
            page_title=f"Label: {label_name} - {BLOG_NAME}",
            canonical_url=permalink_abs,
            custom_css_content=custom_css_content
        )

        # Bangun dokumen HTML lengkap
        full_label_html = build_html_document(label_head_html, label_body_content)
        
        output_path = os.path.join(OUTPUT_DIR, permalink_rel.lstrip('/'))
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_label_html)
        print(f"  > Halaman Label '{label_name}' selesai: {permalink_rel}")

    print("Proses pembangunan situs selesai.")


if __name__ == "__main__":
    if not API_KEY or not BLOG_ID:
        print("Error: Variabel lingkungan BLOGGER_API_KEY atau BLOGGER_BLOG_ID tidak ditemukan.")
        print("Pastikan Anda mengatur mereka di GitHub Actions secrets.")
    else:
        posts_data = get_blogger_data(API_KEY, BLOG_ID)
        if posts_data is not None:
            build_site(posts_data)
        else:
            print("Gagal mengambil data postingan dari Blogger API. Situs tidak dapat dibangun.")
