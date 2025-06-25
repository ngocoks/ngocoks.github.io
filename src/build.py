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
# Ini adalah URL absolut untuk situs Anda, misal: https://ngocoks.github.io
BASE_SITE_URL = "https://ngocoks.github.io" # <<< GANTI INI DENGAN DOMAIN/SUBDOMAIN GITHUB PAGES ANDA!
BLOG_NAME = "Nama Blog Anda" # <<< GANTI DENGAN NAMA BLOG ANDA

# Setup Jinja2 Environment
# Autoescape untuk keamanan XSS di template, kecuali jika di markup dengan 'safe'
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)

# --- FUNGSI BANTUAN ---

def get_snippet(html_content, word_limit=100):
    """Mengekstrak snippet teks bersih dari konten HTML."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')
    text = soup.get_text()
    words = text.split()
    return ' '.join(words[:word_limit]) + ('...' if len(words) > word_limit else '')

def convert_to_amp(html_content):
    """
    Mengonversi HTML biasa ke HTML yang kompatibel dengan AMP.
    Ini adalah fungsi dasar. Untuk konversi yang lebih canggih, pertimbangkan
    pustaka pihak ketiga yang memang khusus untuk AMP.
    """
    if not html_content:
        return ""
    
    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. Ubah img menjadi amp-img
    for img in soup.find_all('img'):
        amp_img = soup.new_tag('amp-img')
        # Salin atribut penting
        for attr, value in img.attrs.items():
            if attr in ['src', 'alt']:
                amp_img[attr] = value
            elif attr == 'width' and str(value).isdigit():
                amp_img[attr] = value
            elif attr == 'height' and str(value).isdigit():
                amp_img[attr] = value
        
        # Berikan width/height default jika tidak ada, atau pastikan numerik
        # Ini penting untuk layout AMP
        if 'width' not in amp_img.attrs: amp_img['width'] = '600'
        if 'height' not in amp_img.attrs: amp_img['height'] = '400'
        
        amp_img['layout'] = 'responsive' # Layout paling umum dan adaptif
        
        img.replace_with(amp_img)

    # 2. Hapus atribut style inline
    for tag in soup.find_all(attrs={'style': True}):
        del tag['style']

    # 3. Hapus script tag (kecuali type="application/ld+json")
    for script_tag in soup.find_all('script'):
        if 'type' in script_tag.attrs and script_tag['type'] == 'application/ld+json':
            continue # Biarkan script JSON-LD
        script_tag.decompose()
        
    # 4. Hapus atribut 'id' dari elemen non-AMP untuk mencegah konflik/validasi AMP
    for tag in soup.find_all(True):
        if 'id' in tag.attrs and not tag.name.startswith('amp-'):
            del tag['id']

    # Membersihkan entitas HTML ganda yang mungkin muncul dari Beautiful Soup
    return str(soup).replace('&amp;', '&')


def generate_breadcrumbs(post_title, post_labels, base_url):
    """Menghasilkan struktur breadcrumbs untuk JSON-LD."""
    breadcrumbs = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": base_url}
    ]
    
    if post_labels and len(post_labels) > 0:
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
            "fields": "items(id,title,url,published,updated,content,labels,images,author(displayName)),nextPageToken"
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

def build_site(posts):
    print("Memulai proses pembangunan situs...")
    
    if not posts:
        print("Tidak ada postingan untuk dibangun. Menghentikan.")
        return

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
    
    # --- Render Halaman Index (dengan PaginasI) ---
    print("Membangun halaman index...")
    index_template = env.get_template("index.html")
    
    posts_per_page = 10
    total_posts = len(sorted_posts)
    total_pages = (total_posts + posts_per_page - 1) // posts_per_page
    
    for page_num in range(1, total_pages + 1):
        start_idx = (page_num - 1) * posts_per_page
        end_idx = start_idx + posts_per_page
        paginated_posts = sorted_posts[start_idx:end_idx]

        processed_posts_for_index = []
        for p in paginated_posts:
            p_copy = p.copy()
            p_copy['snippet'] = get_snippet(p_copy.get('content', ''))
            p_copy['thumbnail_url'] = get_post_image_url(p_copy)
            
            # Permalink untuk artikel langsung di root
            post_slug = slugify(p_copy['title'])
            p_copy['permalink'] = f"/{post_slug}-{p_copy['id']}.html" 
            processed_posts_for_index.append(p_copy)

        # Penentuan URL navigasi halaman di root
        prev_page_url = None
        if page_num > 1:
            if page_num == 2:
                prev_page_url = "/index.html" # Halaman 1 adalah index.html
            else:
                prev_page_url = f"/index_p{page_num-1}.html"
        
        next_page_url = None
        if page_num < total_pages:
            next_page_url = f"/index_p{page_num+1}.html"

        # Tentukan permalink halaman index saat ini untuk canonical
        current_index_permalink = "/index.html" if page_num == 1 else f"/index_p{page_num}.html"
        absolute_index_permalink = f"{BASE_SITE_URL}{current_index_permalink}"

        index_html = index_template.render(
            title="Beranda",
            posts=processed_posts_for_index,
            labels=unique_labels_list,
            current_page=page_num,
            total_pages=total_pages,
            prev_page_url=prev_page_url,
            next_page_url=next_page_url,
            base_site_url=BASE_SITE_URL,
            blog_name=BLOG_NAME,
            permalink=current_index_permalink, # untuk canonical di halaman index
            absolute_permalink=absolute_index_permalink
        )
        
        output_filename = "index.html" if page_num == 1 else f"index_p{page_num}.html"
        with open(os.path.join(OUTPUT_DIR, output_filename), "w", encoding="utf-8") as f:
            f.write(index_html)
        print(f"  > Index Page {page_num}/{total_pages} selesai: {output_filename}")

    # --- Render Halaman Artikel Individual ---
    print("Membangun halaman artikel...")
    post_template = env.get_template("post.html")
    for post in posts:
        post_slug = slugify(post['title'])
        permalink = f"/{post_slug}-{post['id']}.html"
        absolute_permalink = f"{BASE_SITE_URL}{permalink}"
        
        amp_content = convert_to_amp(post.get('content', ''))
        main_image_url = get_post_image_url(post)
        
        # Related Posts (Ambil 3 postingan lain dari label yang sama, jika ada)
        related_posts = []
        if 'labels' in post:
            for label in post['labels']:
                for p_related in sorted_posts:
                    if p_related['id'] != post['id'] and \
                       'labels' in p_related and label in p_related['labels']:
                        p_copy_related = p_related.copy()
                        p_copy_related_slug = slugify(p_copy_related['title'])
                        p_copy_related['permalink'] = f"/{p_copy_related_slug}-{p_copy_related['id']}.html"
                        p_copy_related['thumbnail_url'] = get_post_image_url(p_copy_related)
                        if len(related_posts) < 3 and p_copy_related not in related_posts: # Pastikan unik dan batasi 3
                            related_posts.append(p_copy_related)
                        if len(related_posts) >= 3:
                            break
                if len(related_posts) >= 3:
                    break
        related_posts = related_posts[:3] # Pastikan hanya 3 jika lebih

        # Generate breadcrumbs data
        breadcrumbs_data = generate_breadcrumbs(post['title'], post.get('labels', []), BASE_SITE_URL)

        post_html = post_template.render(
            title=post['title'], # Judul halaman
            post=post,
            amp_content=amp_content,
            permalink=permalink,
            absolute_permalink=absolute_permalink,
            main_image_url=main_image_url,
            related_posts=related_posts,
            breadcrumbs=breadcrumbs_data,
            labels=unique_labels_list,
            base_site_url=BASE_SITE_URL,
            blog_name=BLOG_NAME
        )
        
        with open(os.path.join(OUTPUT_DIR, permalink.lstrip('/')), "w", encoding="utf-8") as f:
            f.write(post_html)
        print(f"  > Artikel selesai: {permalink}")

    # --- Render Halaman Label ---
    print("Membangun halaman label...")
    label_template = env.get_template("label.html")
    for label_name in unique_labels_list:
        label_slug = slugify(label_name)
        label_permalink = f"/{label_slug}.html"
        absolute_label_permalink = f"{BASE_SITE_URL}{label_permalink}"
        
        # Filter postingan untuk label ini
        posts_for_label = [
            p for p in sorted_posts if 'labels' in p and label_name in p['labels']
        ]
        
        processed_label_posts = []
        for p in posts_for_label:
            p_copy = p.copy()
            p_copy['snippet'] = get_snippet(p_copy.get('content', ''))
            p_copy['thumbnail_url'] = get_post_image_url(p_copy)
            
            post_slug = slugify(p_copy['title'])
            p_copy['permalink'] = f"/{post_slug}-{p_copy['id']}.html"
            processed_label_posts.append(p_copy)

        label_html = label_template.render(
            title=f"Label: {label_name}", # Judul halaman
            label_name=label_name,
            posts=processed_label_posts,
            labels=unique_labels_list,
            current_page=1, # Saat ini label tidak dipaginasi
            total_pages=1,
            base_site_url=BASE_SITE_URL,
            blog_name=BLOG_NAME,
            permalink=label_permalink, # untuk canonical di halaman label
            absolute_permalink=absolute_label_permalink
        )
        
        with open(os.path.join(OUTPUT_DIR, label_permalink.lstrip('/')), "w", encoding="utf-8") as f:
            f.write(label_html)
        print(f"  > Halaman Label '{label_name}' selesai: {label_permalink}")

    print("Proses pembangunan situs selesai.")


if __name__ == "__main__":
    if not API_KEY or not BLOG_ID:
        print("Error: Variabel lingkungan BLOGGER_API_KEY atau BLOGGER_BLOG_ID tidak ditemukan.")
        print("Pastikan Anda mengatur mereka di GitHub Actions secrets.")
    else:
        posts_data = get_blogger_data(API_KEY, BLOG_ID)
        if posts_data is not None: # Pastikan data berhasil diambil
            build_site(posts_data)
        else:
            print("Gagal mengambil data postingan dari Blogger API. Situs tidak dapat dibangun.")
