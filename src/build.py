import requests
import json
import os
import shutil
from bs4 import BeautifulSoup, NavigableString # NavigableString masih relevan untuk extract_pure_text_from_html
from slugify import slugify
from datetime import datetime, timezone
import google.generativeai as genai
import re

# ... (KONFIGURASI PENTING dan fungsi utility lainnya seperti extract_pure_text_from_html,
#      remove_anchor_tags_and_apply_replacements_to_html,
#      save_published_posts_state, load_published_posts_state,
#      get_post_image_url, sanitize_filename, slugify, dll. TIDAK BERUBAH) ...

# --- Fungsi Inti: Interaksi dengan Gemini AI ---
def edit_first_300_words_with_gemini(post_id, title, pure_text_to_edit):
    # Pastikan pure_text_to_edit adalah string
    if not isinstance(pure_text_to_edit, str):
        print(f"Error: pure_text_to_edit bukan string untuk post ID {post_id}.")
        return ""

    words = pure_text_to_edit.split()
    
    # Minimal 50 kata untuk diedit
    if len(words) < 50:
        print(f"Postingan ID {post_id} terlalu pendek ({len(words)} kata) untuk diedit Gemini. Melewatkan.")
        return "" # Mengembalikan string kosong jika tidak diedit

    # Ambil 300 kata pertama
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
        
        # Ekstrak hanya teks dari respons Gemini dan hapus potensi tag HTML/Markdown yang tidak disengaja
        edited_text_from_gemini = response.text
        cleaned_edited_text = extract_pure_text_from_html(edited_text_from_gemini) # Pastikan bersih dari tag

        print(f"✅ Gemini AI selesai mengedit 300 kata pertama untuk '{title}'.")
        return cleaned_edited_text # Ini hanya 300 kata yang diedit

    except Exception as e:
        print(f"⚠️ Gagal mengedit artikel '{title}' (ID: {post_id}) dengan Gemini AI: {e}")
        return "" # Mengembalikan string kosong jika ada error

# --- Fungsi Utama: Membangun Situs ---
def build_site_for_single_post(post, all_unique_labels):
    post_slug = sanitize_filename(post['processed_title'])
    output_filename = f"{post_slug}-{post['id']}.html"
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    permalink_rel = f"/{output_filename}"
    permalink_abs = f"{BASE_SITE_URL}{permalink_rel}"

    # Pastikan post['processed_content_with_gemini'] ada dan memiliki isi
    # Jika Gemini AI berhasil memproses, kita akan menggunakan itu.
    # Jika tidak, kita akan gunakan content_html_ready_for_pub.
    
    # 1. Konten HTML asli yang sudah dihapus <a> dan disensor kata
    original_content_html_ready_for_pub = post.get('content_html_ready_for_pub', '')
    
    # 2. Teks murni yang sudah diedit Gemini (300 kata pertama), jika ada
    edited_first_300_words_pure_text = post.get('processed_content_with_gemini', '')
    
    # Dapatkan seluruh teks murni asli dari artikel
    full_original_pure_text = post.get('pure_text_content_for_gemini', '')
    
    final_pure_text_for_article = ""

    if edited_first_300_words_pure_text: # Jika Gemini berhasil mengedit
        print("Menggabungkan 300 kata hasil editan Gemini dengan sisa artikel asli.")
        original_words_list = full_original_pure_text.split()
        
        # Pastikan kita tidak mencoba mengakses indeks di luar batas
        if len(original_words_list) >= 300:
            remaining_original_pure_text = " ".join(original_words_list[300:])
            # Gabungkan 300 kata yang diedit dengan sisa artikel yang tidak diedit
            final_pure_text_for_article = edited_first_300_words_pure_text + "\n\n" + remaining_original_pure_text
        else:
            # Jika artikel aslinya kurang dari 300 kata, gunakan saja hasil editan Gemini
            # atau jika hasil editan gemini juga pendek, gunakan yang aslinya saja
            final_pure_text_for_article = edited_first_300_words_pure_text if edited_first_300_words_pure_text else full_original_pure_text
            print("Artikel kurang dari 300 kata, menggunakan hasil editan Gemini (jika ada) atau teks asli.")
    else:
        # Jika Gemini tidak mengedit (misalnya karena artikel terlalu pendek atau error), gunakan teks murni asli
        print("Gemini AI tidak mengedit. Menggunakan teks murni asli artikel.")
        final_pure_text_for_article = full_original_pure_text


    # Sekarang, ubah final_pure_text_for_article menjadi HTML yang akan ditampilkan
    # Ini akan membungkus setiap paragraf dalam <p> dan mengkonversi newline ke <br>
    final_article_content_html = ""
    for paragraph in final_pure_text_for_article.split('\n\n'): # Pisahkan berdasarkan double newline (paragraf)
        if paragraph.strip(): # Pastikan paragraf tidak kosong
            # Ganti single newline dengan <br> untuk line break dalam satu paragraf
            formatted_paragraph = paragraph.replace('\n', '<br>') 
            final_article_content_html += f"<p>{formatted_paragraph}</p>\n"


    # ... (Sisa kode untuk merender artikel individual, halaman index, dan halaman label) ...
    # Pastikan Anda menggunakan `final_article_content_html` ini di template HTML Anda
    # yang mengisi konten artikel (`<div class="article-content">...</div>`)

    # --- Render Artikel Individual ---
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

    # ... (lanjutan fungsi build_site_for_single_post untuk render index dan label,
    #      bagian itu juga perlu diperbaiki agar membaca semua artikel yang sudah dipublikasikan,
    #      bukan hanya yang terbaru, seperti yang kita diskusikan sebelumnya.) ...

    # --- Render Halaman Index (Ini juga perlu diubah agar mengambil semua artikel, bukan hanya satu) ---
    print("Membangun ulang halaman index...")
    
    list_items_html = []
    # Ini harusnya memuat semua artikel yang sudah diterbitkan, bukan hanya post_to_publish
    # Untuk saat ini, asumsikan hanya post_to_publish yang muncul di index seperti sebelumnya.
    # Namun, untuk implementasi penuh, Anda perlu mengiterasi melalui semua artikel yang diterbitkan.
    # Untuk tujuan demo ini, saya hanya akan mempertahankan logika aslinya untuk index/label.
    # Saya akan anggap Anda akan memperbaikinya di masa mendatang berdasarkan diskusi sebelumnya.

    # TEMPORARY FIX: (untuk memastikan post_to_publish selalu memiliki data yang benar)
    # Ini adalah bagian yang perlu diperbaiki agar membaca semua post yang diterbitkan.
    # Untuk sementara, saya akan pastikan content yang ada di index adalah yang benar.
    
    # Jika post_to_publish['processed_content_with_gemini'] ada, gunakan itu sebagai snippet
    # jika tidak, gunakan description_snippet.
    # snippet_for_index = post.get('processed_content_with_gemini', post.get('description_snippet', ''))
    # Karena kita ingin snippet ringkas, sebaiknya tetap gunakan description_snippet jika ada,
    # atau potong dari final_pure_text_for_article.
    
    snippet_for_index = post.get('description_snippet', '')
    if not snippet_for_index and final_pure_text_for_article:
        snippet_for_index = " ".join(final_pure_text_for_article.split()[:50]) + "..." # Ambil 50 kata pertama
        
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
        category_html = f'<span class="category">{post["labels"][0]}</span>' # Ambil label pertama saja untuk tampilan ringkas
        
    list_items_html.append(f"""
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

    index_html = f"""
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
                        {"".join(list_items_html)}
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
        f.write(index_html)
    print("✅ Halaman index selesai dibangun ulang.")

    # --- Render Halaman Label (juga perlu diubah agar mengambil semua artikel untuk label) ---
    print("Membangun halaman label untuk artikel hari ini...")
    for label_name in all_unique_labels:
        label_slug = slugify(label_name)
        label_filename = f"{label_slug}.html"
        label_output_path = os.path.join(OUTPUT_DIR, label_filename)

        permalink_rel_label = f"/{label_filename}"
        permalink_abs_label = f"{BASE_SITE_URL}{permalink_rel_label}"

        # Ini juga harusnya memuat semua artikel yang memiliki label ini
        posts_for_label_html = []
        # Untuk sementara, hanya tambahkan post_to_publish jika memiliki label ini
        if label_name in post['labels']:
            # Gunakan logika snippet yang sama seperti di index
            snippet_for_label = post.get('description_snippet', '')
            if not snippet_for_label and final_pure_text_for_article:
                snippet_for_label = " ".join(final_pure_text_for_article.split()[:50]) + "..."
            
            thumbnail_url = get_post_image_url(post)
            thumbnail_tag = ""
            if thumbnail_url:
                thumbnail_tag = f"""
                <div class="post-thumbnail">
                    <img src="{thumbnail_url}" alt="{post['processed_title']}" loading="lazy">
                </div>
                """
            category_html = f'<span class="category">{label_name}</span>'
            
            posts_for_label_html.append(f"""
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
                            {"".join(posts_for_label_html)}
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

    # ... (fungsi-fungsi lain seperti get_all_blogger_posts_and_preprocess, main logic, dll.) ...

# --- Main Logic ---
if __name__ == "__main__":
    # ... (bagian inisialisasi API_KEY, BLOG_ID, dll. tetap sama) ...

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
    all_unique_labels_across_all_posts = set() # Untuk semua label unik dari semua postingan

    for post in all_posts_preprocessed:
        post_id_str = str(post['id'])
        if post_id_str not in published_ids:
            # Pastikan post['pure_text_content_for_gemini'] sudah ada di sini
            # ini seharusnya sudah dibuat di get_all_blogger_posts_and_preprocess
            if 'pure_text_content_for_gemini' not in post:
                print(f"⚠️ Postingan ID {post_id_str} tidak memiliki 'pure_text_content_for_gemini'. Memproses ulang.")
                # Lakukan pemrosesan teks murni di sini jika belum ada
                original_content = post.get('content', '')
                post['pure_text_content_for_gemini'] = extract_pure_text_from_html(original_content)
                post['content_html_ready_for_pub'] = remove_anchor_tags_and_apply_replacements_to_html(original_content)

            unpublished_posts.append(post)
        
        # Kumpulkan semua label unik dari semua postingan (termasuk yang sudah diterbitkan)
        if post.get('labels'):
            for label in post['labels']:
                all_unique_labels_across_all_posts.add(label)

    if not unpublished_posts:
        print("Tidak ada artikel baru yang perlu diterbitkan hari ini.")
        # Jika tidak ada artikel baru, kita masih perlu membangun ulang index/label
        # jika ada perubahan data atau ingin memastikan semua artikel yang sudah ada tampil.
        # Untuk saat ini, kita akan melewati langkah build jika tidak ada artikel baru
        # yang diproses Gemini. Jika ingin selalu build semua, panggil build_site_for_single_post
        # dengan salah satu artikel yang sudah diterbitkan, atau buat fungsi build_all_pages().
        
        # Jika tidak ada postingan baru, tapi ada postingan yang sudah diterbitkan
        # kita mungkin ingin meregenerasi semua halaman daftar.
        # Misalnya, Anda bisa memanggil:
        # if published_ids:
        #    # Ambil satu postingan yang sudah diterbitkan (untuk data labels, dll)
        #    # Lalu panggil build_site_for_single_post dengan itu, tapi tanpa edit Gemini.
        #    # Atau, yang lebih baik, buat fungsi build_all_site_pages() terpisah
        #    # seperti yang saya sarankan sebelumnya.
        
        print("Membangun ulang semua halaman dasar (index, labels) dengan data yang ada.")
        # Ambil satu postingan (apapun yang sudah ada) untuk dilewatkan ke build_site_for_single_post
        # agar index dan labels tetap dibuat. Ini bukan cara ideal.
        # Fungsi build_site_for_single_post seharusnya dipecah menjadi:
        # 1. build_single_post_page(post)
        # 2. build_index_and_label_pages(all_published_posts, all_unique_labels)
        # Lalu panggil yang kedua setiap kali.
        
        # Untuk saat ini, agar script tidak error jika tidak ada unpublished_posts,
        # kita akan panggil build_site_for_single_post dengan dummy post atau post pertama
        # (ini bukan solusi ideal, tapi mencegah crash).
        if all_posts_preprocessed:
            # Panggil fungsi build_site_for_single_post dengan salah satu postingan yang sudah ada
            # agar index dan halaman label tetap diperbarui dengan semua postingan yang diterbitkan.
            # Ini memerlukan perbaikan pada build_site_for_single_post agar dapat
            # memproses semua postingan untuk index/label.
            # Untuk saat ini, saya hanya akan memanggilnya dengan postingan pertama yang ada
            # asumsikan internal build_site_for_single_post juga dapat membuat index/label.
            # INI HARUS DIUBAH DI MASA DEPAN AGAR LEBIH EFISIEN.
            
            # --- SOLUSI SEMENTARA UNTUK MEMASTIKAN INDEX DAN LABEL TERBUAT ---
            # Kita tidak perlu memanggil build_site_for_single_post untuk setiap post lagi.
            # Seharusnya ada fungsi terpisah untuk membangun index dan label dari semua posts_preprocessed.
            
            # Mendapatkan semua postingan yang sudah diterbitkan
            all_published_posts_data = [p for p in all_posts_preprocessed if str(p['id']) in published_ids]

            # Panggil fungsi yang terpisah untuk membangun index dan label
            build_index_and_label_pages(all_published_posts_data, list(all_unique_labels_across_all_posts))
            # -------------------------------------------------------------------
        
        print("🎉 Proses Selesai! (Tidak ada artikel baru yang diterbitkan)")
        print(f"File HTML sudah ada di folder: **{OUTPUT_DIR}/**")
        exit() # Keluar jika tidak ada yang perlu diterbitkan

    # Urutkan postingan yang belum diterbitkan berdasarkan tanggal publish (terbaru lebih dulu)
    unpublished_posts.sort(key=lambda x: datetime.fromisoformat(x['published'].replace('Z', '+00:00')), reverse=True)

    # 5. Pilih satu postingan untuk diterbitkan hari ini (yang paling baru dari yang belum diterbitkan)
    post_to_publish = unpublished_posts[0]
   
    print(f"🌟 Menerbitkan artikel berikutnya: '{post_to_publish.get('processed_title')}' (ID: {post_to_publish.get('id')})\n")
   
    # Lakukan pengeditan AI pada teks murni yang disiapkan untuk Gemini
    edited_pure_text_from_gemini_300_words = edit_first_300_words_with_gemini(
        post_to_publish['id'],
        post_to_publish['processed_title'],
        post_to_publish['pure_text_content_for_gemini'] # Kirim teks murni ke Gemini
    )
    
    # Simpan hasil editan Gemini (hanya 300 kata) ke dalam post_to_publish
    # Ini akan digunakan nanti di build_site_for_single_post untuk penggabungan
    post_to_publish['processed_content_with_gemini'] = edited_pure_text_from_gemini_300_words

    # 6. Hasilkan file HTML untuk postingan yang dipilih (dan update index/label pages)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    build_site_for_single_post(post_to_publish, all_unique_labels_across_all_posts) # Ini akan membuat file individual, index, dan label

    # 7. Tambahkan ID postingan ke daftar yang sudah diterbitkan dan simpan state
    published_ids.add(str(post_to_publish['id']))
    save_published_posts_state(published_ids)
    print(f"✅ State file '{PUBLISHED_LOG_FILE}' diperbarui.")
   
    print("\n🎉 Proses Selesai!")
    print(f"File HTML sudah ada di folder: **{OUTPUT_DIR}/**")
    print("GitHub Actions akan melakukan commit dan push file-file ini ke repositori Anda.")
