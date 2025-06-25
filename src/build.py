import requests
import json
import os
from jinja2 import Environment, FileSystemLoader
from bs4 import BeautifulSoup
from slugify import slugify
from datetime import datetime

# --- KONFIGURASI PENTING ---
# Ambil dari variabel lingkungan GitHub Actions (disimpan sebagai GitHub Secrets)
API_KEY = os.getenv("BLOGGER_API_KEY")
BLOG_ID = os.getenv("BLOGGER_BLOG_ID")

# Direktori input/output
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
OUTPUT_DIR = "dist" # Output situs statis yang akan di-deploy ke GitHub Pages

# URL dasar situs Anda di GitHub Pages. GANTI INI DENGAN URL REPO ANDA!
# Contoh: Jika username Anda 'ngocoks' dan nama repo 'blogger-static', maka https://ngocoks.github.io/blogger-static
# Jika Anda menggunakan custom domain atau ngocoks.github.io (tanpa nama repo), pastikan sesuai.
BASE_SITE_URL = "https://ngocoks.github.io" # <<< GANTI INI!

# Pastikan direktori output ada
os.makedirs(OUTPUT_DIR, exist_ok=True)


# Setup Jinja2 Environment
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

# --- FUNGSI BANTUAN (HANYA YANG RELEVAN DENGAN PERUBAHAN) ---

def get_snippet(html_content, word_limit=100):
    """Mengekstrak snippet teks dari konten HTML."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')
    text = soup.get_text()
    words = text.split()
    return ' '.join(words[:word_limit]) + ('...' if len(words) > word_limit else '')

def convert_to_amp(html_content):
    """
    Mengonversi HTML biasa ke HTML yang kompatibel dengan AMP.
    Ini adalah fungsi dasar. Untuk kasus yang lebih kompleks (video, iframe, etc.),
    Anda mungkin perlu pustaka AMP HTML validator/converter yang lebih canggih
    atau menambahkan logika spesifik.
    """
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. Ubah img menjadi amp-img
    for img in soup.find_all('img'):
        amp_img = soup.new_tag('amp-img')
        # Salin atribut penting
        for attr, value in img.attrs.items():
            if attr in ['src', 'alt', 'width', 'height']:
                amp_img[attr] = value
        
        # Berikan width/height default jika tidak ada, atau pastikan numerik
        if 'width' not in amp_img.attrs or not str(amp_img.get('width', '')).isdigit(): amp_img['width'] = '600'
        if 'height' not in amp_img.attrs or not str(amp_img.get('height', '')).isdigit(): amp_img['height'] = '400'
        
        # Tentukan layout, responsive adalah yang paling umum
        amp_img['layout'] = 'responsive'
        
        img.replace_with(amp_img)

    # 2. Hapus atribut style inline (AMP tidak mengizinkan sebagian besar)
    for tag in soup.find_all(attrs={'style': True}):
        del tag['style']

    # 3. Hapus script tag (kecuali type="application/ld+json")
    for script_tag in soup.find_all('script'):
        if 'type' in script_tag.attrs and script_tag['type'] == 'application/ld+json':
            continue # Biarkan script JSON-LD
        script_tag.decompose()
        
    # Hapus atribut yang tidak diizinkan AMP (contoh: id dari elemen selain amp-*)
    for tag in soup.find_all(True):
        if 'id' in tag.attrs and not tag.name.startswith('amp-'):
            del tag['id']

    return str(soup)

def generate_breadcrumbs(post_title, post_labels=None, base_url=""):
    """
    Menghasilkan data breadcrumbs untuk JSON-LD.
    """
    breadcrumbs = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": base_url}
    ]
    if post_labels and len(post_labels) > 0:
        # Ambil label pertama sebagai kategori utama (bisa disesuaikan)
        main_label = post_labels[0]
        breadcrumbs.append({
            "@type": "ListItem",
            "position": 2,
            "name": main_label,
            "item": f"{base_url}/{slugify(main_label)}.html" # URL label di root
        })
        breadcrumbs.append({
            "@type": "ListItem",
            "position": 3,
            "name": post_title,
            "item": "" # URL artikel akan diisi di template (meta position content)
        })
    else:
        # Jika tidak ada label, langsung ke artikel
        breadcrumbs.append({
            "@type": "ListItem",
            "position": 2,
            "name": post_title,
            "item": "" # URL artikel akan diisi di template (meta position content)
        })
    return breadcrumbs

# FUNGSI BARU UNTUK MENGAMBIL URL GAMBAR UTAMA
def get_main_image_url(post_data):
    """Mengekstrak URL gambar utama dari data postingan."""
    if 'images' in post_data and post_data['images']:
        # Mengembalikan URL dari gambar pertama yang disediakan oleh Blogger API
        return post_data['images'][0]['url']
    
    # Fallback: coba ekstrak dari konten HTML jika tidak ada di 'images' API field
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
            "fields": "items(id,title,url,published,updated,content,labels,images,author(displayName)),nextPageToken"
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
                break # No more pages

        except requests.exceptions.HTTPError as e:
            print(f"Error HTTP: {e.response.status_code} - {e.response.text}")
            break
        except requests.exceptions.RequestException as e:
            print(f"Error jaringan: {e}")
            break
    
    print(f"Total {len(all_posts)} postingan berhasil diambil.")
    return all_posts

# --- FUNGSI UTAMA (HANYA BAGIAN YANG BERUBAH) ---
def build_site(posts):
    print("Memulai proses pembangunan situs...")

    all_unique_labels = set()
    for post in posts:
        if 'labels' in post:
            for label in post['labels']:
                all_unique_labels.add(label)
    
    unique_labels_list = sorted(list(all_unique_labels))

    sorted_posts = sorted(posts, key=lambda p: p['published'], reverse=True)
    
    # --- Render Halaman Index (dengan PaginasI) ---
    index_template = env.get_template("index.html")
    posts_per_page = 10
    total_pages = (len(sorted_posts) + posts_per_page - 1) // posts_per_page
    
    for page_num in range(1, total_pages + 1):
        start_idx = (page_num - 1) * posts_per_page
        end_idx = start_idx + posts_per_page
        paginated_posts = sorted_posts[start_idx:end_idx]

        processed_posts = []
        for p in paginated_posts:
            p_copy = p.copy()
            p_copy['snippet'] = get_snippet(p_copy.get('content', ''))
            p_copy['thumbnail_url'] = get_main_image_url(p_copy) # Menggunakan fungsi baru
            
            post_slug = slugify(p_copy['title'])
            p_copy['permalink'] = f"/{post_slug}-{p_copy['id']}.html" 
            processed_posts.append(p_copy)

        prev_page_url = None
        if page_num > 1:
            if page_num == 2:
                prev_page_url = "/index.html"
            else:
                prev_page_url = f"/index_p{page_num-1}.html"
        
        next_page_url = None
        if page_num < total_pages:
            next_page_url = f"/index_p{page_num+1}.html"

        index_html = index_template.render(
            posts=processed_posts,
            labels=unique_labels_list,
            current_page=page_num,
            total_pages=total_pages,
            prev_page_url=prev_page_url,
            next_page_url=next_page_url,
            base_site_url=BASE_SITE_URL
        )
        
        output_filename = "index.html" if page_num == 1 else f"index_p{page_num}.html"
        with open(os.path.join(OUTPUT_DIR, output_filename), "w", encoding="utf-8") as f:
            f.write(index_html)

    # --- Render Halaman Artikel Individual ---
    post_template = env.get_template("post.html")
    for post in posts:
        post_slug = slugify(post['title'])
        permalink = f"/{post_slug}-{post['id']}.html"
        absolute_permalink = f"{BASE_SITE_URL}{permalink}"
        
        amp_content = convert_to_amp(post.get('content', ''))
        main_image_url = get_main_image_url(post) # Menggunakan fungsi baru
        
        # Related Posts (sama seperti sebelumnya, logika tidak berubah)
        related_posts = []
        if 'labels' in post:
            for label in post['labels']:
                for p_related in sorted_posts:
                    if p_related['id'] != post['id'] and \
                       'labels' in p_related and label in p_related['labels']:
                        p_copy_related = p_related.copy()
                        p_copy_related_slug = slugify(p_copy_related['title'])
                        p_copy_related['permalink'] = f"/{p_copy_related_slug}-{p_copy_related['id']}.html"
                        p_copy_related['thumbnail_url'] = get_main_image_url(p_copy_related)
                        if p_copy_related not in related_posts:
                            related_posts.append(p_copy_related)
                        if len(related_posts) >= 3:
                            break
                if len(related_posts) >= 3:
                    break
        related_posts = related_posts[:3]

        breadcrumbs_data = generate_breadcrumbs(post['title'], post.get('labels'), BASE_SITE_URL)

        post_html = post_template.render(
            post=post,
            amp_content=amp_content,
            permalink=permalink,
            absolute_permalink=absolute_permalink,
            main_image_url=main_image_url, # Variabel baru untuk URL gambar utama
            related_posts=related_posts,
            breadcrumbs=breadcrumbs_data,
            labels=unique_labels_list,
            base_site_url=BASE_SITE_URL
        )
        
        with open(os.path.join(OUTPUT_DIR, permalink.lstrip('/')), "w", encoding="utf-8") as f:
            f.write(post_html)

    # --- Render Halaman Label ---
    label_template = env.get_template("label.html")
    for label_name in unique_labels_list:
        label_slug = slugify(label_name)
        label_permalink = f"/{label_slug}.html"
        
        posts_for_label = [
            p for p in sorted_posts if 'labels' in p and label_name in p['labels']
        ]
        
        processed_label_posts = []
        for p in posts_for_label:
            p_copy = p.copy()
            p_copy['snippet'] = get_snippet(p_copy.get('content', ''))
            p_copy['thumbnail_url'] = get_main_image_url(p_copy)
            
            post_slug = slugify(p_copy['title'])
            p_copy['permalink'] = f"/{post_slug}-{p_copy['id']}.html"
            processed_label_posts.append(p_copy)

        label_html = label_template.render(
            label_name=label_name,
            posts=processed_label_posts,
            labels=unique_labels_list,
            current_page=1,
            total_pages=1,
            base_site_url=BASE_SITE_URL
        )
        
        with open(os.path.join(OUTPUT_DIR, label_permalink.lstrip('/')), "w", encoding="utf-8") as f:
            f.write(label_html)

    print("Proses pembangunan situs selesai.")


if __name__ == "__main__":
    if not API_KEY or not BLOG_ID:
        print("Error: Variabel lingkungan BLOGGER_API_KEY atau BLOGGER_BLOG_ID tidak ditemukan.")
        print("Pastikan Anda mengatur mereka di GitHub Actions secrets.")
    else:
        posts_data = get_blogger_data(API_KEY, BLOG_ID)
        if posts_data:
            build_site(posts_data)
        else:
            print("Tidak ada postingan yang ditemukan atau ada masalah saat mengambil data.")
