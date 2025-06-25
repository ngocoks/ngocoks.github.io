import requests
import json
import os
from jinja2 import Environment, FileSystemLoader
from bs4 import BeautifulSoup
from slugify import slugify
from datetime import datetime

# --- KONFIGURASI ---
# Ambil dari variabel lingkungan GitHub Actions
API_KEY = os.getenv("BLOGGER_API_KEY")
BLOG_ID = os.getenv("BLOGGER_BLOG_ID")

# Direktori input/output
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
OUTPUT_DIR = "dist" # Output situs statis

# Pastikan direktori output ada
os.makedirs(OUTPUT_DIR, exist_ok=True)


# Setup Jinja2 Environment
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

# --- FUNGSI BANTUAN ---
def get_snippet(html_content, word_limit=100):
    """Mengekstrak snippet teks dari konten HTML."""
    soup = BeautifulSoup(html_content, 'html.parser')
    text = soup.get_text()
    words = text.split()
    return ' '.join(words[:word_limit]) + ('...' if len(words) > word_limit else '')

def convert_to_amp(html_content):
    """
    Mengonversi HTML biasa ke HTML yang kompatibel dengan AMP.
    Ini adalah fungsi yang SANGAT sederhana dan mungkin perlu ditingkatkan
    untuk kasus penggunaan yang kompleks (misalnya, iframe, video, custom components).
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. Ubah img menjadi amp-img
    for img in soup.find_all('img'):
        amp_img = soup.new_tag('amp-img')
        for attr, value in img.attrs.items():
            if attr in ['src', 'alt']: # Copy essential attributes
                amp_img[attr] = value
            elif attr == 'width' and value.isdigit():
                amp_img[attr] = value # Keep width if it's a digit
            elif attr == 'height' and value.isdigit():
                amp_img[attr] = value # Keep height if it's a digit
        # Jika width/height tidak ada, berikan nilai default atau placeholder
        if 'width' not in amp_img.attrs: amp_img['width'] = '600'
        if 'height' not in amp_img.attrs: amp_img['height'] = '400'
        amp_img['layout'] = 'responsive' # Default layout
        img.replace_with(amp_img)

    # 2. Hapus atribut style inline (AMP tidak mengizinkan sebagian besar)
    for tag in soup.find_all(attrs={'style': True}):
        del tag['style']

    # 3. Hapus script tag (kecuali type="application/ld+json")
    for script_tag in soup.find_all('script'):
        if 'type' in script_tag.attrs and script_tag['type'] == 'application/ld+json':
            continue # Biarkan script JSON-LD
        script_tag.decompose()

    return str(soup)

def generate_breadcrumbs(post_title, post_labels=None, base_url=""):
    """
    Menghasilkan data breadcrumbs untuk JSON-LD.
    """
    breadcrumbs = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": base_url}
    ]
    if post_labels:
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
            "item": "" # URL akan ditambahkan di template
        })
    else:
        breadcrumbs.append({
            "@type": "ListItem",
            "position": 2,
            "name": post_title,
            "item": "" # URL akan ditambahkan di template
        })
    return breadcrumbs

# --- FUNGSI UTAMA ---
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
            "fields": "items(id,title,url,published,updated,content,labels,images),nextPageToken"
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

def build_site(posts):
    print("Memulai proses pembangunan situs...")

    # Kumpulkan semua label unik
    all_unique_labels = set()
    for post in posts:
        if 'labels' in post:
            for label in post['labels']:
                all_unique_labels.add(label)
    
    unique_labels_list = sorted(list(all_unique_labels))
    print(f"Ditemukan {len(unique_labels_list)} label unik.")

    # Base URL for the GitHub Pages site (GANTI INI SESUAI REPO ANDA)
    # Jika ngocoks.github.io, maka base_url = "https://ngocoks.github.io"
    # Jika ngocoks.github.io/your-repo-name, maka base_url = "https://ngocoks.github.io/your-repo-name"
    # Untuk skenario root domain, ini adalah base URL absolut.
    BASE_SITE_URL = "https://ngocoks.github.io" # GANTI INI DENGAN DOMAIN ROOT ANDA

    # Render Halaman Index
    print("Membangun halaman index...")
    index_template = env.get_template("index.html")
    # Urutkan postingan berdasarkan tanggal publikasi terbaru
    sorted_posts = sorted(posts, key=lambda p: p['published'], reverse=True)
    
    # Pagination untuk Index Page (contoh sederhana, bisa lebih kompleks)
    posts_per_page = 10
    total_pages = (len(sorted_posts) + posts_per_page - 1) // posts_per_page
    
    for page_num in range(1, total_pages + 1):
        start_idx = (page_num - 1) * posts_per_page
        end_idx = start_idx + posts_per_page
        paginated_posts = sorted_posts[start_idx:end_idx]

        # Tambahkan snippet dan thumbnail ke setiap postingan
        processed_posts = []
        for p in paginated_posts:
            p_copy = p.copy() # Hindari memodifikasi objek post asli
            p_copy['snippet'] = get_snippet(p_copy.get('content', ''))
            # Coba ambil gambar thumbnail, bisa dari 'images' atau ekstrak dari konten
            if 'images' in p_copy and p_copy['images']:
                p_copy['thumbnail_url'] = p_copy['images'][0]['url']
            else:
                # Fallback: coba ekstrak dari konten jika tidak ada di 'images'
                soup = BeautifulSoup(p_copy.get('content', ''), 'html.parser')
                first_img = soup.find('img')
                if first_img and 'src' in first_img.attrs:
                    p_copy['thumbnail_url'] = first_img['src']
                else:
                    p_copy['thumbnail_url'] = "" # No thumbnail found

            # Buat permalink yang rapi untuk ROOT
            post_slug = slugify(p_copy['title'])
            # URL artikel langsung di root
            p_copy['permalink'] = f"/{post_slug}-{p_copy['id']}.html" 
            processed_posts.append(p_copy)

        index_html = index_template.render(
            posts=processed_posts,
            labels=unique_labels_list,
            current_page=page_num,
            total_pages=total_pages,
            # URL navigasi halaman di root
            prev_page_url=f"/index_p{page_num-1}.html" if page_num > 1 and page_num-1 > 1 else "/index.html" if page_num == 2 else None,
            next_page_url=f"/index_p{page_num+1}.html" if page_num < total_pages else None
        )
        
        output_filename = "index.html" if page_num == 1 else f"index_p{page_num}.html"
        with open(os.path.join(OUTPUT_DIR, output_filename), "w", encoding="utf-8") as f:
            f.write(index_html)
        print(f"  > Index Page {page_num} selesai: {output_filename}")


    # Render Halaman Artikel Individual
    print("Membangun halaman artikel...")
    post_template = env.get_template("post.html")
    for post in posts:
        post_slug = slugify(post['title'])
        # Permalink untuk artikel langsung di root
        permalink = f"/{post_slug}-{post['id']}.html"
        
        # Konversi konten ke AMP
        amp_content = convert_to_amp(post.get('content', ''))

        # Related Posts (Contoh Sederhana: ambil 3 postingan lain dari label yang sama)
        related_posts = []
        if 'labels' in post:
            for label in post['labels']:
                for p in posts:
                    if p['id'] != post['id'] and 'labels' in p and label in p['labels']:
                        p_copy = p.copy()
                        p_copy_slug = slugify(p_copy['title'])
                        p_copy['permalink'] = f"/{p_copy_slug}-{p_copy['id']}.html" # Permalink related posts juga di root
                        if 'images' in p_copy and p_copy['images']:
                            p_copy['thumbnail_url'] = p_copy['images'][0]['url']
                        else:
                            soup = BeautifulSoup(p_copy.get('content', ''), 'html.parser')
                            first_img = soup.find('img')
                            p_copy['thumbnail_url'] = first_img['src'] if first_img and 'src' in first_img.attrs else ""
                        related_posts.append(p_copy)
                        if len(related_posts) >= 3: # Batasi 3 related posts
                            break
                if len(related_posts) >= 3:
                    break
        
        # Generate breadcrumbs data (gunakan BASE_SITE_URL)
        breadcrumbs_data = generate_breadcrumbs(post['title'], post.get('labels'), BASE_SITE_URL)

        post_html = post_template.render(
            post=post,
            amp_content=amp_content,
            permalink=permalink, # Permalink relatif
            absolute_permalink=f"{BASE_SITE_URL}{permalink}", # Permalink absolut
            related_posts=related_posts,
            breadcrumbs=breadcrumbs_data,
            labels=unique_labels_list # Untuk menu navigasi
        )
        
        # Simpan file di root OUTPUT_DIR
        with open(os.path.join(OUTPUT_DIR, permalink.lstrip('/')), "w", encoding="utf-8") as f:
            f.write(post_html)
        print(f"  > Artikel selesai: {permalink}")

    # Render Halaman Label
    print("Membangun halaman label...")
    label_template = env.get_template("label.html")
    for label_name in unique_labels_list:
        label_slug = slugify(label_name)
        # Permalink untuk label langsung di root
        label_permalink = f"/{label_slug}.html"
        
        # Filter postingan untuk label ini
        posts_for_label = [
            p for p in posts if 'labels' in p and label_name in p['labels']
        ]
        # Proses postingan untuk snippet dan thumbnail
        processed_label_posts = []
        for p in sorted(posts_for_label, key=lambda p: p['published'], reverse=True):
            p_copy = p.copy()
            p_copy['snippet'] = get_snippet(p_copy.get('content', ''))
            if 'images' in p_copy and p_copy['images']:
                p_copy['thumbnail_url'] = p_copy['images'][0]['url']
            else:
                soup = BeautifulSoup(p_copy.get('content', ''), 'html.parser')
                first_img = soup.find('img')
                p_copy['thumbnail_url'] = first_img['src'] if first_img and 'src' in first_img.attrs else ""
            
            post_slug = slugify(p_copy['title'])
            p_copy['permalink'] = f"/{post_slug}-{p_copy['id']}.html" # Permalink juga di root
            processed_label_posts.append(p_copy)

        label_html = label_template.render(
            label_name=label_name,
            posts=processed_label_posts,
            labels=unique_labels_list, # Untuk menu navigasi
            current_page=1, # Sederhana, tanpa paginasi untuk label dulu
            total_pages=1
        )
        
        # Simpan file di root OUTPUT_DIR
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
        if posts_data:
            build_site(posts_data)
        else:
            print("Tidak ada postingan yang ditemukan atau ada masalah saat mengambil data.")
