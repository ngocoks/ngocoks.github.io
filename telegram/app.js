// --- KONFIGURASI API KEY DAN BLOG ID ANDA ---
const BLOG_ID = '8601707668889540603';
const API_KEY = 'AIzaSyBglonTK3lbLZwqYKSuI3Vj64HUbdPWq6s'; // PERHATIKAN: API KEY INI AKAN TERLIHAT DI CLIENT-SIDE.
                                                          // Untuk aplikasi produksi, disarankan menggunakan backend untuk proxy API.

const BLOGGER_API_BASE_URL = `https://www.googleapis.com/blogger/v3/blogs/${BLOG_ID}/posts?key=${API_KEY}`;

// --- DOM Elements ---
const storyListSection = document.getElementById('story-list-section');
const storyDetailSection = document.getElementById('story-detail-section');
const storyTitleElement = document.getElementById('story-title');
const storyAuthorElement = document.getElementById('story-author');
const storyContentElement = document.getElementById('story-content');
const backButton = document.getElementById('back-button');

// --- Inisialisasi Telegram Web App SDK ---
document.addEventListener('DOMContentLoaded', () => {
    if (window.Telegram && window.Telegram.WebApp) {
        const WebApp = window.Telegram.WebApp;

        WebApp.ready();
        WebApp.expand(); // Perluas Mini App ke seluruh layar

        // Opsional: Sesuaikan warna tema Mini App dengan tema Telegram
        if (WebApp.themeParams) {
            document.documentElement.style.setProperty('--tg-theme-bg-color', WebApp.themeParams.bg_color);
            document.documentElement.style.setProperty('--tg-theme-secondary-bg-color', WebApp.themeParams.secondary_bg_color);
            document.documentElement.style.setProperty('--tg-theme-text-color', WebApp.themeParams.text_color);
            document.documentElement.style.setProperty('--tg-theme-hint-color', WebApp.themeParams.hint_color);
            document.documentElement.style.setProperty('--tg-theme-link-color', WebApp.themeParams.link_color);
            document.documentElement.style.setProperty('--tg-theme-button-color', WebApp.themeParams.button_color);
            document.documentElement.style.setProperty('--tg-theme-button-text-color', WebApp.themeParams.button_text_color);
        }

        console.log('Telegram Web App SDK siap!');
        loadStories(); // Mulai memuat daftar cerita
        
    } else {
        console.error('Telegram Web App SDK tidak ditemukan. Pastikan Anda membuka ini di Telegram.');
        document.body.innerHTML = `
            <div class="container" style="text-align: center; padding: 20px;">
                <h1>Akses Langsung Tidak Didukung</h1>
                <p>Harap buka aplikasi ini melalui Telegram.</p>
                <p>Kunjungi <a href="https://t.me/your_bot_username" target="_blank">bot Telegram Anda</a> untuk mencoba Mini App ini.</p>
            </div>
        `;
    }
});

// --- Fungsi untuk Memuat Daftar Cerita ---
async function loadStories() {
    storyDetailSection.style.display = 'none'; // Sembunyikan detail
    storyListSection.style.display = 'block';  // Tampilkan daftar

    storyListSection.innerHTML = '<h1>Memuat Cerita...</h1><p>Silakan tunggu sebentar.</p>'; // Pesan loading

    try {
        const response = await fetch(BLOGGER_API_BASE_URL);
        if (!response.ok) {
            throw new Error(`Gagal memuat cerita: ${response.status} ${response.statusText}`);
        }
        const data = await response.json();

        if (data.items && data.items.length > 0) {
            const ul = document.createElement('ul');
            data.items.forEach(post => {
                const listItem = document.createElement('li');
                const link = document.createElement('a');
                link.href = '#'; // Gunakan hash agar tidak reload halaman
                link.dataset.postId = post.id;
                link.textContent = post.title;
                link.addEventListener('click', (e) => {
                    e.preventDefault();
                    loadStoryDetail(post.id); // Panggil fungsi detail
                });
                listItem.appendChild(link);
                ul.appendChild(listItem);
            });
            storyListSection.innerHTML = '<h1>Daftar Cerita:</h1>';
            storyListSection.appendChild(ul);
        } else {
            storyListSection.innerHTML = '<h1>Daftar Cerita</h1><p>Belum ada cerita yang tersedia di blog ini.</p>';
        }

    } catch (error) {
        console.error('Error memuat daftar cerita:', error);
        storyListSection.innerHTML = `<h1 style="color: red;">Error!</h1><p>Gagal memuat cerita. (${error.message})</p><p>Pastikan API Key dan Blog ID Anda benar, dan blog Anda memiliki postingan publik.</p>`;
        if (window.Telegram && window.Telegram.WebApp) {
            window.Telegram.WebApp.showAlert(`Gagal memuat daftar cerita: ${error.message}`);
        }
    }
}

// --- Fungsi untuk Memuat Detail Cerita ---
async function loadStoryDetail(postId) {
    storyListSection.style.display = 'none';   // Sembunyikan daftar
    storyDetailSection.style.display = 'block';// Tampilkan detail

    storyTitleElement.textContent = 'Memuat...';
    storyAuthorElement.textContent = '';
    storyContentElement.innerHTML = '<p>Silakan tunggu...</p>';

    try {
        const detailUrl = `https://www.googleapis.com/blogger/v3/blogs/${BLOG_ID}/posts/${postId}?key=${API_KEY}`;
        const response = await fetch(detailUrl);
        if (!response.ok) {
            throw new Error(`Gagal memuat detail: ${response.status} ${response.statusText}`);
        }
        const data = await response.json();

        storyTitleElement.textContent = data.title;
        storyAuthorElement.textContent = `Oleh: ${data.author.displayName}`;
        storyContentElement.innerHTML = data.content; // Konten HTML dari Blogger

    } catch (error) {
        console.error('Error memuat detail cerita:', error);
        storyTitleElement.textContent = 'Error!';
        storyAuthorElement.textContent = '';
        storyContentElement.innerHTML = `<p style="color: red;">Gagal memuat detail cerita. (${error.message})</p>`;
        if (window.Telegram && window.Telegram.WebApp) {
            window.Telegram.WebApp.showAlert(`Gagal memuat detail cerita: ${error.message}`);
        }
    }
}

// --- Event Listener Tombol Kembali ---
backButton.addEventListener('click', loadStories);
