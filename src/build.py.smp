import requests
import json
import os
import shutil
from bs4 import BeautifulSoup
from slugify import slugify
from datetime import datetime

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

# Pastikan direktori output ada
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- FUNGSI BANTUAN ---

def get_snippet(html_content, word_limit=30):
    """Mengekstrak snippet teks bersih dari konten HTML."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')
    text = soup.get_text(separator=' ', strip=True)
    words = text.split()
    return ' '.join(words[:word_limit]) + ('...' if len(words) > word_limit else '')

# Fungsi ini akan dihapus/disederhanakan karena kita tidak lagi mengonversi ke AMP
# def convert_to_amp(html_content):
#     # ... (fungsi ini tidak lagi relevan)
#     pass

def convert_to_standard_html(html_content):
    """
    Mengonversi konten HTML yang mungkin berasal dari AMP (atau HTML biasa)
    ke HTML standar dengan penyesuaian untuk tampilan web umum.
    """
    if not html_content:
        return ""
    
    soup = BeautifulSoup(html_content, 'html.parser')

    # Ubah amp-img menjadi img
    for amp_img in soup.find_all('amp-img'):
        img = soup.new_tag('img')
        for attr, value in amp_img.attrs.items():
            if attr in ['src', 'alt']:
                img[attr] = value
            # Salin width/height jika ada, tapi tidak wajib seperti di AMP
            elif attr == 'width' or attr == 'height':
                img[attr] = value
        amp_img.replace_with(img)

    # Hapus atribut style inline (tetap relevan untuk kebersihan)
    for tag in soup.find_all(attrs={'style': True}):
        del tag['style']

    # Hapus script tag (kecuali type="application/ld+json")
    for script_tag in soup.find_all('script'):
        if 'type' in script_tag.attrs and script_tag['type'] == 'application/ld+json':
            continue
        script_tag.decompose()
            
    # Hapus atribut 'id' yang mungkin tidak diperlukan atau konflik
    for tag in soup.find_all(True):
        if 'id' in tag.attrs and not tag.name.startswith('amp-'): # 'amp-' check mungkin tidak diperlukan lagi
            del tag['id']
            
    # Hapus elemen yang tidak valid (tetap relevan untuk membersihkan konten dari Blogger)
    invalid_tags = ['iframe', 'form', 'input', 'video', 'audio', 'object', 'embed']
    for tag_name in invalid_tags:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    cleaned_html = str(soup)
    cleaned_html = cleaned_html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
    return cleaned_html

def generate_breadcrumbs_data(post_title, post_labels, base_url):
    """Menghasilkan struktur breadcrumbs untuk JSON-LD."""
    breadcrumbs = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": base_url}
    ]
    
    if post_labels:
        main_label = post_labels[0]
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
            "item": ""
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
        
    soup = BeautifulSoup(post_data.get('content', ''), 'html.parser')
    first_img = soup.find('img')
    if first_img and 'src' in first_img.attrs:
        return first_img['src']
    return ""

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
            "maxResults": 500,
            "fields": "items(id,title,url,published,updated,content,labels,images,author(displayName),replies(totalItems)),nextPageToken"
        }
        if next_page_token:
            params["pageToken"] = next_page_token

        try:
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
    
    print(f"Total {len(all_posts)} postingan berhasil diambil.")
    return all_posts

# --- Fungsi untuk Membangun Bagian HTML ---

def build_head_content(page_title, canonical_url, custom_css_content):
    """Membangun bagian <head> dari dokumen HTML."""
    head_html = f"""
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="canonical" href="{canonical_url}">
    <title>{page_title}</title>
    <meta name="google-site-verification" content="wxkvpqMwTAGfQ5E0xjycz-q-Elshg4pLh8B_7JhzgGk" />

    <style>
        {custom_css_content}
    </style>
    <script>
        document.addEventListener('DOMContentLoaded', function() {{
            const hamburger = document.querySelector('.hamburger');
            const closeButton = document.querySelector('.close-button');
            const sidebar = document.getElementById('sidebar-menu');

            if (hamburger) {{
                hamburger.addEventListener('click', function() {{
                    sidebar.classList.toggle('active');
                }});
            }}

            if (closeButton) {{
                closeButton.addEventListener('click', function() {{
                    sidebar.classList.remove('active');
                }});
            }}
        }});
    </script>
    """
    return head_html

def build_header_and_sidebar(all_labels, current_blog_name):
    """Membangun bagian header dan sidebar navigasi."""
    logo_tag = ""
    if os.path.exists(LOGO_PATH):
        # Menggunakan tag img standar
        logo_tag = f'<img src="{BASE_SITE_URL}/logo.png" width="80" height="40" alt="Logo Blog">'

    header_html = f"""
    <header class="header">
        <button class="hamburger" aria-label="Open navigation">☰</button>
        <h1><a href="/">{logo_tag} {current_blog_name}</a></h1>
        <div class="search-icon">
        </div>
    </header>

    <nav id="sidebar-menu" class="sidebar">
        <button class="close-button" aria-label="Close navigation">✕</button>
        <ul>
            <li><a href="/">Beranda</a></li>
            {"".join([f'<li><a href="/{slugify(label)}.html">{label}</a></li>' for label in all_labels])}
        </ul>
    </nav>
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
    """Membangun struktur dasar dokumen HTML standar."""
    return f"""
<!DOCTYPE html>
<html lang="en">
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
                # Menggunakan tag img standar
                thumbnail_tag = f"""
                <div class="post-thumbnail">
                    <img src="{thumbnail_url}" alt="{p['title']}" loading="lazy">
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
        current_index_permalink_rel = "/" if page_num == 1 else f"/index_p{page_num}.html"
        current_index_permalink_abs = f"{BASE_SITE_URL}{current_index_permalink_rel}"

        # Tambahkan ruang iklan di sini (tetap sama)
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
        
        # Gunakan fungsi konversi ke HTML biasa
        standard_content = convert_to_standard_html(post.get('content', ''))
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
                    # Menggunakan tag img standar
                    rp_thumbnail_tag = f"""
                    <div class="related-thumbnail">
                        <img src="{rp['thumbnail_url']}" alt="{rp['title']}" loading="lazy">
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

        # Breadcrumbs data untuk JSON-LD (tetap sama)
        breadcrumbs_data = generate_breadcrumbs_data(post['title'], post_labels, BASE_SITE_URL)
        breadcrumbs_json = json.dumps(breadcrumbs_data)

        # HTML untuk Breadcrumbs di halaman (tetap sama)
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

        # HTML untuk labels di bawah artikel (tetap sama)
        labels_html = ""
        if post_labels:
            labels_links = [f'<a href="/{slugify(label)}.html">{label}</a>' for label in post_labels]
            labels_html = f"<br>Labels: {', '.join(labels_links)}"

        # JSON-LD untuk artikel (tetap sama)
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
                    {standard_content}
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
                # Menggunakan tag img standar
                thumbnail_tag = f"""
                <div class="post-thumbnail">
                    <img src="{thumbnail_url}" alt="{p['title']}" loading="lazy">
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
