import os
import shutil
import json
import pandas as pd
import re

def build_database():
    src_dir = r"c:\Users\dwain\Downloads\New folder (3)\taberu_extract"
    dest_dir = r"c:\Users\dwain\Downloads\New folder (3)\menu_visual_db"
    
    src_images_dir = os.path.join(src_dir, "menu_images_final")
    dest_images_dir = os.path.join(dest_dir, "menu_images")
    
    print(f"Creating directories at: {dest_dir}")
    os.makedirs(dest_dir, exist_ok=True)
    os.makedirs(dest_images_dir, exist_ok=True)
    
    # 1. Copy images
    print("Copying images from taberu_extract/menu_images_final to menu_visual_db/menu_images...")
    copied_count = 0
    if os.path.exists(src_images_dir):
        for filename in os.listdir(src_images_dir):
            src_file = os.path.join(src_images_dir, filename)
            dest_file = os.path.join(dest_images_dir, filename)
            if os.path.isfile(src_file):
                shutil.copy2(src_file, dest_file)
                copied_count += 1
    print(f"Copied {copied_count} menu images.")
    
    # 2. Parse CSVs
    print("Reading and merging CSV files...")
    df_ja = pd.read_csv(os.path.join(src_dir, "menu_items_japanese_compliant.csv"))
    df_en = pd.read_csv(os.path.join(src_dir, "menu_items_compliant.csv"))
    menu_map = pd.read_csv(os.path.join(src_dir, "menu_image_map.csv"))
    
    # Create image mapping dictionary: menu_id -> list of relative image filenames
    image_dict = {}
    for idx, row in menu_map.iterrows():
        menu_id = str(row['menu_id']).strip()
        img_files_str = str(row['image_files'])
        if pd.isna(row['image_files']) or not img_files_str.strip():
            image_dict[menu_id] = []
            continue
        # Split by pipe and extract basenames
        files = [os.path.basename(f.strip()) for f in img_files_str.split('|') if f.strip()]
        image_dict[menu_id] = files
        
    # Merge JA and EN datasets
    # Columns to keep from JA: menu_id, item_id, restaurant_name, item_name (ja), price, price_tax_incl, currency, description (ja), menu_image, menu_all_pages
    df_ja = df_ja.rename(columns={'item_name': 'item_name_ja', 'description': 'description_ja'})
    df_en = df_en.rename(columns={'item_name': 'item_name_en', 'description': 'description_en'})
    
    # Merge on item_id
    merged_items = pd.merge(
        df_ja[['menu_id', 'item_id', 'restaurant_name', 'item_name_ja', 'price', 'price_tax_incl', 'currency', 'description_ja']],
        df_en[['item_id', 'item_name_en', 'description_en']],
        on='item_id',
        how='left'
    )
    
    # Fill NaNs
    merged_items['price_tax_incl'] = merged_items['price_tax_incl'].fillna('')
    merged_items['description_ja'] = merged_items['description_ja'].fillna('')
    merged_items['description_en'] = merged_items['description_en'].fillna('')
    merged_items['item_name_en'] = merged_items['item_name_en'].fillna('')
    
    # 3. Group by store
    print("Grouping items by store...")
    stores = {}
    for idx, row in merged_items.iterrows():
        menu_id = str(row['menu_id']).strip()
        if menu_id not in stores:
            # Check if this store has images mapped
            imgs = image_dict.get(menu_id, [])
            stores[menu_id] = {
                'id': menu_id,
                'name': str(row['restaurant_name']).strip(),
                'images': imgs,
                'items': []
            }
            
        stores[menu_id]['items'].append({
            'id': str(row['item_id']).strip(),
            'name_ja': str(row['item_name_ja']).strip(),
            'name_en': str(row['item_name_en']).strip(),
            'price': float(row['price']) if not pd.isna(row['price']) else 0.0,
            'price_tax_incl': float(row['price_tax_incl']) if row['price_tax_incl'] != '' else None,
            'currency': str(row['currency']).strip(),
            'desc_ja': str(row['description_ja']).strip(),
            'desc_en': str(row['description_en']).strip()
        })
        
    # Convert stores dict to sorted list by store name or id
    stores_list = sorted(list(stores.values()), key=lambda x: x['id'])
    
    # 4. Write db_data.js
    db_js_path = os.path.join(dest_dir, "db_data.js")
    print(f"Writing database file to: {db_js_path}")
    
    # Serialize JSON with formatting for readability but still compact
    db_json = json.dumps({'stores': stores_list}, ensure_ascii=False, indent=2)
    with open(db_js_path, 'w', encoding='utf-8') as f:
        f.write(f"window.MENU_DB = {db_json};\n")
        
    print("Successfully generated db_data.js.")
    
    # 5. Write HTML, CSS, and JS frontend files
    write_frontend_files(dest_dir)

def write_frontend_files(dest_dir):
    # HTML content
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Japan Menu Visual Database</title>
    <!-- Google Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div class="app-layout">
        <!-- Sidebar Navigation -->
        <aside class="sidebar">
            <div class="sidebar-header">
                <div class="logo">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="logo-icon"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
                    <h2>Menu Visual DB</h2>
                </div>
                <div class="database-stats" id="db-stats">
                    Loading stats...
                </div>
            </div>
            
            <div class="search-section">
                <div class="search-box">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="search-icon"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                    <input type="text" id="store-search" placeholder="Search stores...">
                </div>
                
                <div class="filter-toggles">
                    <label class="filter-chip">
                        <input type="checkbox" id="filter-has-images" checked>
                        <span>With Images</span>
                    </label>
                    <label class="filter-chip">
                        <input type="checkbox" id="filter-no-images" checked>
                        <span>No Images</span>
                    </label>
                </div>
            </div>
            
            <div class="store-list" id="store-list-container">
                <!-- Store items rendered by JS -->
            </div>
        </aside>
        
        <!-- Main Content Area -->
        <main class="main-content">
            <!-- Mode Switcher -->
            <div class="top-nav">
                <div class="tab-group">
                    <button class="tab-btn active" id="tab-store">Store Browser</button>
                    <button class="tab-btn" id="tab-global-search">Global Item Search</button>
                </div>
            </div>
            
            <!-- Store Browser View -->
            <div id="store-browser-view" class="view-panel active">
                <div class="no-store-selected" id="no-store-placeholder">
                    <div class="placeholder-content">
                        <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="9" y1="3" x2="9" y2="21"></line><line x1="9" y1="9" x2="21" y2="9"></line><line x1="9" y1="15" x2="21" y2="15"></line></svg>
                        <h3>Select a restaurant from the sidebar</h3>
                        <p>Browse their menu items, pricing, and high-quality scanned menu pages.</p>
                    </div>
                </div>
                
                <div class="store-details-container" id="store-details" style="display: none;">
                    <div class="store-header-card">
                        <div class="store-meta">
                            <span class="store-badge" id="detail-store-id">NVM0001</span>
                            <h1 id="detail-store-name">82 ALE HOUSE GRAND</h1>
                        </div>
                        <div class="store-actions">
                            <!-- Link placeholders or additional info -->
                        </div>
                    </div>
                    
                    <!-- Menu Images Section (If Available) -->
                    <div class="menu-images-section" id="detail-images-section">
                        <h3>Menu Scans / Images</h3>
                        <div class="gallery-grid" id="detail-gallery-grid">
                            <!-- Thumbnails filled by JS -->
                        </div>
                    </div>
                    
                    <!-- Items Section -->
                    <div class="items-section">
                        <div class="items-header">
                            <h3>Menu Items</h3>
                            <div class="item-search-box">
                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="search-icon"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                                <input type="text" id="item-search" placeholder="Filter items in this menu...">
                            </div>
                        </div>
                        
                        <div class="items-grid-container">
                            <table class="items-table">
                                <thead>
                                    <tr>
                                        <th>ID</th>
                                        <th>Name (Japanese)</th>
                                        <th>Name (English)</th>
                                        <th style="text-align: right;">Price</th>
                                        <th>Description/Tag</th>
                                    </tr>
                                </thead>
                                <tbody id="detail-items-tbody">
                                    <!-- Rows filled by JS -->
                                </tbody>
                            </table>
                            <div class="pagination-controls" id="item-pagination">
                                <!-- Pagination controls -->
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Global Item Search View -->
            <div id="global-search-view" class="view-panel">
                <div class="global-search-header">
                    <h2>Global Item Search</h2>
                    <p>Search through all 19,356 menu items across all stores in the database.</p>
                    <div class="global-search-box">
                        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="search-icon"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                        <input type="text" id="global-item-search" placeholder="Search by name, English name, tag, or description...">
                    </div>
                    <div class="global-search-filters">
                        <div class="filter-group">
                            <label for="global-price-min">Price range (JPY):</label>
                            <input type="number" id="global-price-min" placeholder="Min" min="0">
                            <span>to</span>
                            <input type="number" id="global-price-max" placeholder="Max" min="0">
                        </div>
                    </div>
                </div>
                
                <div class="global-results-section">
                    <div class="results-meta" id="global-results-meta">
                        Enter a keyword to start searching.
                    </div>
                    <div class="items-grid-container">
                        <table class="items-table">
                            <thead>
                                <tr>
                                    <th>Store</th>
                                    <th>Item ID</th>
                                    <th>Name (Japanese)</th>
                                    <th>Name (English)</th>
                                    <th style="text-align: right;">Price</th>
                                    <th>Description/Tag</th>
                                    <th>Action</th>
                                </tr>
                            </thead>
                            <tbody id="global-results-tbody">
                                <!-- Results filled by JS -->
                            </tbody>
                        </table>
                        <div class="pagination-controls" id="global-pagination">
                            <!-- Pagination controls -->
                        </div>
                    </div>
                </div>
            </div>
        </main>
    </div>
    
    <!-- Lightbox Overlay for Image Inspection -->
    <div class="lightbox" id="lightbox-overlay">
        <button class="lightbox-close" id="lightbox-close-btn">&times;</button>
        <button class="lightbox-btn lightbox-prev" id="lightbox-prev-btn">&#10094;</button>
        <button class="lightbox-btn lightbox-next" id="lightbox-next-btn">&#10095;</button>
        
        <div class="lightbox-content-wrapper">
            <div class="lightbox-img-container" id="lightbox-img-container">
                <img id="lightbox-img" src="" alt="Menu Image" draggable="false">
            </div>
        </div>
        
        <div class="lightbox-controls">
            <button class="ctrl-btn" id="zoom-in-btn">Zoom In</button>
            <button class="ctrl-btn" id="zoom-out-btn">Zoom Out</button>
            <button class="ctrl-btn" id="zoom-reset-btn">Reset</button>
            <span class="lightbox-page-num" id="lightbox-page-info">Page 1 of 1</span>
        </div>
    </div>
    
    <!-- Load pre-compiled JS database -->
    <script src="db_data.js"></script>
    <script src="app.js"></script>
</body>
</html>
"""
    
    # CSS content
    css_content = """/* Root Variables & Colors */
:root {
    --bg-dark: #0f172a;
    --bg-sidebar: #1e293b;
    --bg-card: rgba(30, 41, 59, 0.7);
    --border-color: rgba(255, 255, 255, 0.08);
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --accent-cyan: #0ea5e9;
    --accent-teal: #0d9488;
    --accent-emerald: #10b981;
    --accent-rose: #f43f5e;
    --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
    --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
    --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1);
}

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    background-color: var(--bg-dark);
    color: var(--text-primary);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    height: 100vh;
    overflow: hidden;
    -webkit-font-smoothing: antialiased;
}

/* App Layout Grid */
.app-layout {
    display: grid;
    grid-template-columns: 360px 1fr;
    height: 100vh;
    width: 100vw;
}

/* Sidebar Styling */
.sidebar {
    background-color: var(--bg-sidebar);
    border-right: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
}

.sidebar-header {
    padding: 1.5rem;
    border-bottom: 1px solid var(--border-color);
}

.logo {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.5rem;
}

.logo-icon {
    color: var(--accent-cyan);
}

.logo h2 {
    font-family: 'Outfit', sans-serif;
    font-weight: 700;
    font-size: 1.25rem;
    letter-spacing: -0.025em;
    background: linear-gradient(135deg, var(--text-primary) 30%, var(--accent-cyan));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.database-stats {
    font-size: 0.8rem;
    color: var(--text-secondary);
    font-weight: 500;
}

.search-section {
    padding: 1rem 1.5rem;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
}

.search-box {
    position: relative;
    display: flex;
    align-items: center;
}

.search-icon {
    position: absolute;
    left: 0.75rem;
    color: var(--text-muted);
}

.search-box input {
    width: 100%;
    background-color: rgba(15, 23, 42, 0.6);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 0.6rem 0.75rem 0.6rem 2.25rem;
    color: var(--text-primary);
    font-size: 0.9rem;
    transition: all 0.2s ease;
}

.search-box input:focus {
    outline: none;
    border-color: var(--accent-cyan);
    box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.2);
}

.filter-toggles {
    display: flex;
    gap: 0.5rem;
}

.filter-chip {
    cursor: pointer;
    display: inline-flex;
    align-items: center;
}

.filter-chip input {
    display: none;
}

.filter-chip span {
    background-color: rgba(15, 23, 42, 0.4);
    border: 1px solid var(--border-color);
    border-radius: 100px;
    padding: 0.35rem 0.75rem;
    font-size: 0.8rem;
    font-weight: 500;
    color: var(--text-secondary);
    transition: all 0.2s ease;
}

.filter-chip input:checked + span {
    background-color: rgba(14, 165, 233, 0.15);
    border-color: var(--accent-cyan);
    color: var(--accent-cyan);
}

.store-list {
    flex: 1;
    overflow-y: auto;
    padding: 0.5rem 0;
}

/* Store Cards */
.store-card {
    padding: 0.85rem 1.5rem;
    cursor: pointer;
    border-bottom: 1px solid rgba(255, 255, 255, 0.02);
    transition: all 0.15s ease;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
}

.store-card:hover {
    background-color: rgba(255, 255, 255, 0.03);
}

.store-card.active {
    background-color: rgba(14, 165, 233, 0.08);
    border-left: 3px solid var(--accent-cyan);
    padding-left: calc(1.5rem - 3px);
}

.store-card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 0.5rem;
}

.store-card-name {
    font-size: 0.925rem;
    font-weight: 600;
    line-height: 1.35;
    color: var(--text-primary);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

.store-card-id {
    font-family: monospace;
    font-size: 0.75rem;
    color: var(--text-muted);
}

.store-card-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 0.25rem;
}

.store-card-count {
    font-size: 0.775rem;
    color: var(--text-secondary);
}

.img-badge {
    border-radius: 4px;
    padding: 0.15rem 0.4rem;
    font-size: 0.7rem;
    font-weight: 600;
}

.img-badge.has-img {
    background-color: rgba(16, 185, 129, 0.15);
    color: var(--accent-emerald);
}

.img-badge.no-img {
    background-color: rgba(255, 255, 255, 0.05);
    color: var(--text-muted);
}

/* Main Content Styling */
.main-content {
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
}

.top-nav {
    height: 56px;
    background-color: var(--bg-sidebar);
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    padding: 0 2rem;
}

.tab-group {
    display: flex;
    gap: 1rem;
}

.tab-btn {
    background: none;
    border: none;
    color: var(--text-secondary);
    font-size: 0.95rem;
    font-weight: 600;
    cursor: pointer;
    padding: 0.5rem 0.25rem;
    position: relative;
    transition: color 0.2s ease;
}

.tab-btn:hover {
    color: var(--text-primary);
}

.tab-btn.active {
    color: var(--accent-cyan);
}

.tab-btn.active::after {
    content: '';
    position: absolute;
    bottom: -10px;
    left: 0;
    right: 0;
    height: 3px;
    background-color: var(--accent-cyan);
    border-radius: 100px;
}

/* View Panels */
.view-panel {
    flex: 1;
    overflow-y: auto;
    display: none;
    padding: 2rem;
}

.view-panel.active {
    display: block;
}

/* Placeholder State */
.no-store-selected {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-secondary);
    text-align: center;
}

.placeholder-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1rem;
    max-width: 320px;
}

.placeholder-content svg {
    color: var(--text-muted);
}

.placeholder-content h3 {
    color: var(--text-primary);
    font-family: 'Outfit', sans-serif;
    font-weight: 600;
}

.placeholder-content p {
    font-size: 0.9rem;
    line-height: 1.5;
}

/* Store details layout */
.store-details-container {
    display: flex;
    flex-direction: column;
    gap: 2rem;
}

.store-header-card {
    background: var(--bg-card);
    backdrop-filter: blur(8px);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1.5rem 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.store-meta {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
}

.store-badge {
    font-family: monospace;
    font-size: 0.8rem;
    color: var(--accent-cyan);
    background-color: rgba(14, 165, 233, 0.1);
    border: 1px solid rgba(14, 165, 233, 0.2);
    border-radius: 4px;
    padding: 0.15rem 0.5rem;
    align-self: flex-start;
}

.store-meta h1 {
    font-family: 'Outfit', sans-serif;
    font-weight: 700;
    font-size: 1.75rem;
    letter-spacing: -0.02em;
}

/* Menu Images Gallery */
.menu-images-section h3,
.items-section h3,
.global-search-header h2 {
    font-family: 'Outfit', sans-serif;
    font-size: 1.2rem;
    font-weight: 600;
    margin-bottom: 1rem;
    color: var(--text-primary);
}

.gallery-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 1.25rem;
}

.gallery-card {
    background-color: rgba(255, 255, 255, 0.02);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    overflow: hidden;
    cursor: pointer;
    transition: all 0.2s ease;
}

.gallery-card:hover {
    transform: translateY(-4px);
    border-color: rgba(14, 165, 233, 0.4);
    box-shadow: var(--shadow-md);
}

.gallery-img-wrapper {
    height: 240px;
    background-color: #0b0f19;
    position: relative;
}

.gallery-img-wrapper img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    opacity: 0.85;
    transition: opacity 0.2s ease;
}

.gallery-card:hover img {
    opacity: 1;
}

.gallery-info {
    padding: 0.5rem 0.75rem;
    font-size: 0.8rem;
    color: var(--text-secondary);
    font-weight: 500;
    text-align: center;
    border-top: 1px solid var(--border-color);
}

/* Items Section */
.items-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
}

.items-header h3 {
    margin-bottom: 0;
}

.item-search-box {
    position: relative;
    display: flex;
    align-items: center;
    width: 280px;
}

.item-search-box .search-icon {
    position: absolute;
    left: 0.75rem;
    color: var(--text-muted);
}

.item-search-box input {
    width: 100%;
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 0.45rem 0.75rem 0.45rem 2rem;
    color: var(--text-primary);
    font-size: 0.85rem;
    transition: all 0.2s ease;
}

.item-search-box input:focus {
    outline: none;
    border-color: var(--accent-cyan);
}

/* Items Table */
.items-grid-container {
    background-color: rgba(255, 255, 255, 0.01);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    overflow: hidden;
}

.items-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
    text-align: left;
}

.items-table th {
    background-color: rgba(255, 255, 255, 0.03);
    color: var(--text-secondary);
    font-weight: 600;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border-color);
}

.items-table td {
    padding: 0.85rem 1rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
    vertical-align: middle;
}

.items-table tr:last-child td {
    border-bottom: none;
}

.items-table tr:hover td {
    background-color: rgba(255, 255, 255, 0.02);
}

.item-id-cell {
    font-family: monospace;
    font-size: 0.75rem;
    color: var(--text-muted);
}

.item-price-cell {
    font-weight: 600;
    color: var(--text-primary);
    text-align: right;
}

.item-desc-tag {
    display: inline-block;
    background-color: rgba(255, 255, 255, 0.04);
    border-radius: 4px;
    padding: 0.15rem 0.4rem;
    font-size: 0.75rem;
    color: var(--text-secondary);
    max-width: 250px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.item-desc-tag:hover {
    white-space: normal;
    word-break: break-all;
    max-width: none;
}

.item-en-name {
    color: var(--text-secondary);
    font-size: 0.825rem;
    margin-top: 0.15rem;
}

.highlight {
    background-color: rgba(14, 165, 233, 0.25);
    color: #fff;
    padding: 0.1rem 0.2rem;
    border-radius: 2px;
}

/* Pagination Styles */
.pagination-controls {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem 1rem;
    border-top: 1px solid var(--border-color);
    background-color: rgba(255, 255, 255, 0.02);
}

.pagination-stats {
    font-size: 0.8rem;
    color: var(--text-secondary);
}

.pagination-buttons {
    display: flex;
    gap: 0.5rem;
}

.pagination-btn {
    background-color: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    border-radius: 4px;
    padding: 0.3rem 0.6rem;
    font-size: 0.8rem;
    cursor: pointer;
    transition: all 0.2s ease;
}

.pagination-btn:hover:not(:disabled) {
    background-color: rgba(14, 165, 233, 0.15);
    border-color: var(--accent-cyan);
    color: var(--accent-cyan);
}

.pagination-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}

/* Global Search Specific */
.global-search-header {
    background-color: var(--bg-sidebar);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1.5rem 2rem;
    margin-bottom: 1.5rem;
}

.global-search-box {
    position: relative;
    display: flex;
    align-items: center;
    margin-top: 1rem;
    margin-bottom: 1rem;
}

.global-search-box .search-icon {
    position: absolute;
    left: 1rem;
    color: var(--text-muted);
}

.global-search-box input {
    width: 100%;
    background-color: rgba(15, 23, 42, 0.8);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 0.8rem 1rem 0.8rem 2.75rem;
    color: var(--text-primary);
    font-size: 1rem;
    transition: all 0.2s ease;
}

.global-search-box input:focus {
    outline: none;
    border-color: var(--accent-cyan);
    box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
}

.global-search-filters {
    display: flex;
    gap: 1.5rem;
}

.filter-group {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
    color: var(--text-secondary);
}

.filter-group input {
    background-color: rgba(15, 23, 42, 0.6);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 0.35rem 0.5rem;
    color: var(--text-primary);
    width: 90px;
    font-size: 0.85rem;
}

.results-meta {
    font-size: 0.9rem;
    color: var(--text-secondary);
    margin-bottom: 1rem;
    font-weight: 500;
}

.view-store-btn {
    background-color: rgba(14, 165, 233, 0.15);
    border: 1px solid rgba(14, 165, 233, 0.3);
    color: var(--accent-cyan);
    border-radius: 4px;
    padding: 0.25rem 0.6rem;
    font-size: 0.8rem;
    cursor: pointer;
    font-weight: 600;
    transition: all 0.2s ease;
}

.view-store-btn:hover {
    background-color: var(--accent-cyan);
    color: #fff;
}

/* Lightbox Modal */
.lightbox {
    display: none;
    position: fixed;
    z-index: 9999;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    background-color: rgba(10, 15, 30, 0.95);
    overflow: hidden;
}

.lightbox.active {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
}

.lightbox-close {
    position: absolute;
    top: 1.5rem;
    right: 2rem;
    color: var(--text-primary);
    background: none;
    border: none;
    font-size: 2.5rem;
    font-weight: 300;
    cursor: pointer;
    line-height: 1;
    z-index: 10002;
    transition: color 0.2s ease;
}

.lightbox-close:hover {
    color: var(--accent-rose);
}

.lightbox-btn {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    background-color: rgba(0, 0, 0, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: var(--text-primary);
    font-size: 2rem;
    padding: 1.25rem 1rem;
    cursor: pointer;
    border-radius: 6px;
    z-index: 10001;
    transition: all 0.2s ease;
}

.lightbox-btn:hover {
    background-color: var(--accent-cyan);
    color: #fff;
}

.lightbox-prev {
    left: 2rem;
}

.lightbox-next {
    right: 2rem;
}

.lightbox-content-wrapper {
    flex: 1;
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    position: relative;
}

.lightbox-img-container {
    max-width: 90%;
    max-height: 85%;
    display: flex;
    justify-content: center;
    align-items: center;
    cursor: grab;
    user-select: none;
    transition: transform 0.1s ease;
}

.lightbox-img-container img {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    border-radius: 4px;
    box-shadow: 0 25px 50px -12px rgb(0 0 0 / 0.5);
}

.lightbox-img-container:active {
    cursor: grabbing;
}

.lightbox-controls {
    height: 70px;
    width: 100%;
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 1rem;
    border-top: 1px solid rgba(255, 255, 255, 0.05);
    background-color: rgba(15, 23, 42, 0.8);
    z-index: 10000;
}

.ctrl-btn {
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: var(--text-primary);
    padding: 0.5rem 1rem;
    border-radius: 4px;
    font-size: 0.85rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s ease;
}

.ctrl-btn:hover {
    background-color: var(--accent-cyan);
    border-color: var(--accent-cyan);
}

.lightbox-page-num {
    font-size: 0.875rem;
    color: var(--text-secondary);
    margin-left: 1rem;
}

/* Custom Scrollbars */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}

::-webkit-scrollbar-track {
    background: transparent;
}

::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.1);
    border-radius: 100px;
}

::-webkit-scrollbar-thumb:hover {
    background: rgba(255, 255, 255, 0.2);
}
"""
    
    # App.js content
    app_content = """// Application state
const state = {
    stores: [],
    filteredStores: [],
    selectedStore: null,
    
    // Store Browser items pagination
    itemPage: 1,
    itemPageSize: 100,
    itemFilterQuery: '',
    
    // Global items search
    globalSearchQuery: '',
    globalSearchResults: [],
    globalSearchPage: 1,
    globalSearchPageSize: 100,
    globalPriceMin: null,
    globalPriceMax: null,
    
    // Lightbox image viewer
    currentImageIndex: 0,
    zoomScale: 1,
    panX: 0,
    panY: 0,
    isDragging: false,
    startX: 0,
    startY: 0
};

// Initialisation
document.addEventListener('DOMContentLoaded', () => {
    // Load database from window object
    if (window.MENU_DB && window.MENU_DB.stores) {
        state.stores = window.MENU_DB.stores;
    } else {
        console.error("Database db_data.js not loaded or invalid.");
        document.getElementById('db-stats').textContent = "Failed to load database";
        return;
    }
    
    // Compute database stats
    const totalStores = state.stores.length;
    const totalItems = state.stores.reduce((acc, s) => acc + s.items.length, 0);
    const storesWithImages = state.stores.filter(s => s.images.length > 0).length;
    
    document.getElementById('db-stats').innerHTML = `
        <span>Stores: <strong>${totalStores}</strong></span> &bull; 
        <span>Items: <strong>${totalItems.toLocaleString()}</strong></span><br>
        <span>With Images: <strong>${storesWithImages}</strong></span>
    `;
    
    state.filteredStores = [...state.stores];
    
    // Bind Event Listeners
    initEventListeners();
    
    // Initial Render of Sidebar
    renderStoreList();
});

// Event Listeners binding
function initEventListeners() {
    // Sidebar search and filters
    document.getElementById('store-search').addEventListener('input', handleStoreSearch);
    document.getElementById('filter-has-images').addEventListener('change', handleStoreSearch);
    document.getElementById('filter-no-images').addEventListener('change', handleStoreSearch);
    
    // Tab switching
    document.getElementById('tab-store').addEventListener('click', () => switchTab('store'));
    document.getElementById('tab-global-search').addEventListener('click', () => switchTab('global'));
    
    // Detail item filter
    document.getElementById('item-search').addEventListener('input', handleItemFilter);
    
    // Global item search inputs
    document.getElementById('global-item-search').addEventListener('input', handleGlobalSearch);
    document.getElementById('global-price-min').addEventListener('input', handleGlobalSearch);
    document.getElementById('global-price-max').addEventListener('input', handleGlobalSearch);
    
    // Lightbox Controls
    const overlay = document.getElementById('lightbox-overlay');
    const closeBtn = document.getElementById('lightbox-close-btn');
    const prevBtn = document.getElementById('lightbox-prev-btn');
    const nextBtn = document.getElementById('lightbox-next-btn');
    
    closeBtn.addEventListener('click', closeLightbox);
    prevBtn.addEventListener('click', () => navigateLightbox(-1));
    nextBtn.addEventListener('click', () => navigateLightbox(1));
    
    // Close lightbox on clicking backdrop
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay || e.target.id === 'lightbox-img-container') {
            closeLightbox();
        }
    });
    
    // Lightbox zoom buttons
    document.getElementById('zoom-in-btn').addEventListener('click', () => zoomLightbox(1.2));
    document.getElementById('zoom-out-btn').addEventListener('click', () => zoomLightbox(0.85));
    document.getElementById('zoom-reset-btn').addEventListener('click', resetZoom);
    
    // Lightbox key listeners
    document.addEventListener('keydown', (e) => {
        if (!overlay.classList.contains('active')) return;
        if (e.key === 'Escape') closeLightbox();
        if (e.key === 'ArrowLeft') navigateLightbox(-1);
        if (e.key === 'ArrowRight') navigateLightbox(1);
    });
    
    // Drag to Pan Image logic
    const imgContainer = document.getElementById('lightbox-img-container');
    imgContainer.addEventListener('mousedown', startDrag);
    window.addEventListener('mousemove', drag);
    window.addEventListener('mouseup', endDrag);
    
    // Mouse wheel zoom
    imgContainer.addEventListener('wheel', (e) => {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.1 : 0.9;
        zoomLightbox(factor);
    });
}

// Sidebar Render
function renderStoreList() {
    const listContainer = document.getElementById('store-list-container');
    listContainer.innerHTML = '';
    
    if (state.filteredStores.length === 0) {
        listContainer.innerHTML = '<div style="padding: 2rem; text-align: center; color: var(--text-muted);">No stores found.</div>';
        return;
    }
    
    state.filteredStores.forEach(store => {
        const hasImgs = store.images.length > 0;
        const isActive = state.selectedStore && state.selectedStore.id === store.id;
        
        const card = document.createElement('div');
        card.className = `store-card ${isActive ? 'active' : ''}`;
        card.addEventListener('click', () => selectStore(store.id));
        
        card.innerHTML = `
            <div class="store-card-header">
                <span class="store-card-name">${escapeHTML(store.name)}</span>
                <span class="store-card-id">${store.id}</span>
            </div>
            <div class="store-card-footer">
                <span class="store-card-count">${store.items.length} items</span>
                <span class="img-badge ${hasImgs ? 'has-img' : 'no-img'}">
                    ${hasImgs ? `${store.images.length} ${store.images.length === 1 ? 'Page' : 'Pages'}` : 'No Image'}
                </span>
            </div>
        `;
        
        listContainer.appendChild(card);
    });
}

// Handle search and checkbox inputs for Store List
function handleStoreSearch() {
    const query = document.getElementById('store-search').value.toLowerCase().trim();
    const showHasImages = document.getElementById('filter-has-images').checked;
    const showNoImages = document.getElementById('filter-no-images').checked;
    
    state.filteredStores = state.stores.filter(store => {
        const nameMatches = store.name.toLowerCase().includes(query) || store.id.toLowerCase().includes(query);
        const hasImgs = store.images.length > 0;
        
        if (!nameMatches) return false;
        if (hasImgs && !showHasImages) return false;
        if (!hasImgs && !showNoImages) return false;
        
        return true;
    });
    
    renderStoreList();
}

// Select a store to browse
function selectStore(storeId) {
    const store = state.stores.find(s => s.id === storeId);
    if (!store) return;
    
    state.selectedStore = store;
    state.itemPage = 1;
    state.itemFilterQuery = '';
    document.getElementById('item-search').value = '';
    
    // Highlight in sidebar list
    const cards = document.querySelectorAll('.store-card');
    cards.forEach((card, idx) => {
        const currentStore = state.filteredStores[idx];
        if (currentStore && currentStore.id === storeId) {
            card.classList.add('active');
        } else {
            card.classList.remove('active');
        }
    });
    
    // Render store panels
    document.getElementById('no-store-placeholder').style.display = 'none';
    const detailPanel = document.getElementById('store-details');
    detailPanel.style.display = 'flex';
    
    document.getElementById('detail-store-id').textContent = store.id;
    document.getElementById('detail-store-name').textContent = store.name;
    
    // Render images gallery
    const imgSection = document.getElementById('detail-images-section');
    const galleryGrid = document.getElementById('detail-gallery-grid');
    galleryGrid.innerHTML = '';
    
    if (store.images.length > 0) {
        imgSection.style.display = 'block';
        store.images.forEach((imgName, index) => {
            const card = document.createElement('div');
            card.className = 'gallery-card';
            card.addEventListener('click', () => openLightbox(index));
            
            card.innerHTML = `
                <div class="gallery-img-wrapper">
                    <img src="menu_images/${imgName}" alt="Menu image page ${index + 1}" loading="lazy">
                </div>
                <div class="gallery-info">Page ${index + 1}</div>
            `;
            galleryGrid.appendChild(card);
        });
    } else {
        imgSection.style.display = 'none';
    }
    
    // Render items list
    renderStoreItems();
}

// Render items for selected store
function renderStoreItems() {
    const tbody = document.getElementById('detail-items-tbody');
    tbody.innerHTML = '';
    
    if (!state.selectedStore) return;
    
    // Filter store items locally
    const q = state.itemFilterQuery.toLowerCase().trim();
    const filteredItems = state.selectedStore.items.filter(item => {
        return item.name_ja.toLowerCase().includes(q) || 
               item.name_en.toLowerCase().includes(q) || 
               item.id.toLowerCase().includes(q) ||
               item.desc_ja.toLowerCase().includes(q) || 
               item.desc_en.toLowerCase().includes(q);
    });
    
    const totalItems = filteredItems.length;
    const startIdx = (state.itemPage - 1) * state.itemPageSize;
    const endIdx = Math.min(startIdx + state.itemPageSize, totalItems);
    
    const pageItems = filteredItems.slice(startIdx, endIdx);
    
    if (pageItems.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; padding: 2rem; color: var(--text-muted);">No items found in this store menu.</td></tr>`;
        renderPagination('item-pagination', totalItems, state.itemPage, state.itemPageSize, changeItemPage);
        return;
    }
    
    pageItems.forEach(item => {
        const row = document.createElement('tr');
        row.id = `item-row-${item.id}`;
        
        const priceFormatted = item.price.toLocaleString() + ' ' + item.currency;
        const taxBadge = item.price_tax_incl ? `<div style="font-size:0.75rem; color: var(--text-muted); margin-top:0.1rem;">Incl: ¥${item.price_tax_incl.toLocaleString()}</div>` : '';
        
        row.innerHTML = `
            <td class="item-id-cell">${highlightText(item.id, q)}</td>
            <td style="font-weight: 500;">${highlightText(item.name_ja, q)}</td>
            <td>
                <div style="font-weight: 450;">${highlightText(item.name_en, q)}</div>
            </td>
            <td class="item-price-cell">
                <div>${priceFormatted}</div>
                ${taxBadge}
            </td>
            <td>
                ${item.desc_ja ? `<span class="item-desc-tag" title="${escapeHTML(item.desc_ja)}">${highlightText(item.desc_ja, q)}</span>` : ''}
                ${item.desc_en ? `<span class="item-desc-tag" style="margin-left:0.25rem; font-style:italic;" title="${escapeHTML(item.desc_en)}">${highlightText(item.desc_en, q)}</span>` : ''}
            </td>
        `;
        tbody.appendChild(row);
    });
    
    renderPagination('item-pagination', totalItems, state.itemPage, state.itemPageSize, changeItemPage);
}

function handleItemFilter() {
    state.itemFilterQuery = document.getElementById('item-search').value;
    state.itemPage = 1;
    renderStoreItems();
}

function changeItemPage(newPage) {
    state.itemPage = newPage;
    renderStoreItems();
}

// Render pagination utility
function renderPagination(containerId, totalCount, currentPage, pageSize, callbackName) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    
    if (totalCount <= pageSize) {
        return;
    }
    
    const totalPages = Math.ceil(totalCount / pageSize);
    const startIdx = (currentPage - 1) * pageSize + 1;
    const endIdx = Math.min(startIdx + pageSize - 1, totalCount);
    
    const statsSpan = document.createElement('span');
    statsSpan.className = 'pagination-stats';
    statsSpan.textContent = `Showing ${startIdx}-${endIdx} of ${totalCount.toLocaleString()}`;
    
    const btnGroup = document.createElement('div');
    btnGroup.className = 'pagination-buttons';
    
    const prevBtn = document.createElement('button');
    prevBtn.className = 'pagination-btn';
    prevBtn.disabled = currentPage === 1;
    prevBtn.textContent = 'Prev';
    prevBtn.addEventListener('click', () => callbackName(currentPage - 1));
    
    const nextBtn = document.createElement('button');
    nextBtn.className = 'pagination-btn';
    nextBtn.disabled = currentPage === totalPages;
    nextBtn.textContent = 'Next';
    nextBtn.addEventListener('click', () => callbackName(currentPage + 1));
    
    btnGroup.appendChild(prevBtn);
    
    // Let's add current page / total pages info
    const pageIndicator = document.createElement('span');
    pageIndicator.style.fontSize = '0.8rem';
    pageIndicator.style.color = 'var(--text-secondary)';
    pageIndicator.style.alignSelf = 'center';
    pageIndicator.style.margin = '0 0.5rem';
    pageIndicator.textContent = `${currentPage} / ${totalPages}`;
    btnGroup.appendChild(pageIndicator);
    
    btnGroup.appendChild(nextBtn);
    
    container.appendChild(statsSpan);
    container.appendChild(btnGroup);
}

// Global Tab Switching
function switchTab(tabType) {
    const btnStore = document.getElementById('tab-store');
    const btnGlobal = document.getElementById('tab-global-search');
    
    const panelStore = document.getElementById('store-browser-view');
    const panelGlobal = document.getElementById('global-search-view');
    
    if (tabType === 'store') {
        btnStore.classList.add('active');
        btnGlobal.classList.remove('active');
        panelStore.classList.add('active');
        panelGlobal.classList.remove('active');
    } else {
        btnStore.classList.remove('active');
        btnGlobal.classList.add('active');
        panelStore.classList.remove('active');
        panelGlobal.classList.add('active');
        
        // Auto focus global search input
        document.getElementById('global-item-search').focus();
    }
}

// Handle global item search
function handleGlobalSearch() {
    const query = document.getElementById('global-item-search').value.toLowerCase().trim();
    const minPriceStr = document.getElementById('global-price-min').value;
    const maxPriceStr = document.getElementById('global-price-max').value;
    
    const minPrice = minPriceStr ? parseFloat(minPriceStr) : null;
    const maxPrice = maxPriceStr ? parseFloat(maxPriceStr) : null;
    
    state.globalSearchQuery = query;
    state.globalPriceMin = minPrice;
    state.globalPriceMax = maxPrice;
    state.globalSearchPage = 1;
    
    if (!query && minPrice === null && maxPrice === null) {
        document.getElementById('global-results-tbody').innerHTML = '';
        document.getElementById('global-pagination').innerHTML = '';
        document.getElementById('global-results-meta').textContent = 'Enter a keyword or price criteria to start searching.';
        return;
    }
    
    // Execute query across all items in all stores
    const results = [];
    state.stores.forEach(store => {
        store.items.forEach(item => {
            // Text query matches
            let textMatch = true;
            if (query) {
                textMatch = item.name_ja.toLowerCase().includes(query) || 
                            item.name_en.toLowerCase().includes(query) || 
                            item.id.toLowerCase().includes(query) || 
                            item.desc_ja.toLowerCase().includes(query) || 
                            item.desc_en.toLowerCase().includes(query) ||
                            store.name.toLowerCase().includes(query);
            }
            
            if (!textMatch) return;
            
            // Price range check
            if (minPrice !== null && item.price < minPrice) return;
            if (maxPrice !== null && item.price > maxPrice) return;
            
            results.push({
                storeId: store.id,
                storeName: store.name,
                item: item
            });
        });
    });
    
    state.globalSearchResults = results;
    renderGlobalSearchResults();
}

// Render results for global item search
function renderGlobalSearchResults() {
    const tbody = document.getElementById('global-results-tbody');
    tbody.innerHTML = '';
    
    const results = state.globalSearchResults;
    const totalResults = results.length;
    
    document.getElementById('global-results-meta').textContent = `Found ${totalResults.toLocaleString()} matching items.`;
    
    if (totalResults === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 2rem; color: var(--text-muted);">No items matched your search criteria.</td></tr>`;
        document.getElementById('global-pagination').innerHTML = '';
        return;
    }
    
    const startIdx = (state.globalSearchPage - 1) * state.globalSearchPageSize;
    const endIdx = Math.min(startIdx + state.globalSearchPageSize, totalResults);
    
    const pageResults = results.slice(startIdx, endIdx);
    const q = state.globalSearchQuery;
    
    pageResults.forEach(res => {
        const item = res.item;
        const row = document.createElement('tr');
        
        const priceFormatted = item.price.toLocaleString() + ' ' + item.currency;
        const taxBadge = item.price_tax_incl ? `<div style="font-size:0.75rem; color: var(--text-muted); margin-top:0.1rem;">Incl: ¥${item.price_tax_incl.toLocaleString()}</div>` : '';
        
        row.innerHTML = `
            <td style="font-weight: 600; font-size:0.85rem; color: var(--accent-cyan); cursor: pointer;" onclick="jumpToStore('${res.storeId}', '${item.id}')">
                ${highlightText(res.storeName, q)}
            </td>
            <td class="item-id-cell">${highlightText(item.id, q)}</td>
            <td style="font-weight: 500;">${highlightText(item.name_ja, q)}</td>
            <td>
                <div style="font-weight: 450;">${highlightText(item.name_en, q)}</div>
            </td>
            <td class="item-price-cell">
                <div>${priceFormatted}</div>
                ${taxBadge}
            </td>
            <td>
                ${item.desc_ja ? `<span class="item-desc-tag" title="${escapeHTML(item.desc_ja)}">${highlightText(item.desc_ja, q)}</span>` : ''}
                ${item.desc_en ? `<span class="item-desc-tag" style="margin-left:0.25rem; font-style:italic;" title="${escapeHTML(item.desc_en)}">${highlightText(item.desc_en, q)}</span>` : ''}
            </td>
            <td>
                <button class="view-store-btn" onclick="jumpToStore('${res.storeId}', '${item.id}')">Inspect</button>
            </td>
        `;
        tbody.appendChild(row);
    });
    
    renderPagination('global-pagination', totalResults, state.globalSearchPage, state.globalSearchPageSize, changeGlobalPage);
}

function changeGlobalPage(newPage) {
    state.globalSearchPage = newPage;
    renderGlobalSearchResults();
}

// Navigates from global search click directly to the store menu item and highlights it
function jumpToStore(storeId, itemId) {
    // Select tab store browser
    switchTab('store');
    
    // Select store
    selectStore(storeId);
    
    // If store needs to filter or scroll, do it after brief render timeout
    setTimeout(() => {
        // Find which page the item is on
        const store = state.selectedStore;
        if (!store) return;
        
        const q = state.itemFilterQuery.toLowerCase().trim();
        const filteredItems = store.items.filter(item => {
            return item.name_ja.toLowerCase().includes(q) || 
                   item.name_en.toLowerCase().includes(q) || 
                   item.id.toLowerCase().includes(q) ||
                   item.desc_ja.toLowerCase().includes(q) || 
                   item.desc_en.toLowerCase().includes(q);
        });
        
        const itemIdx = filteredItems.findIndex(item => item.id === itemId);
        if (itemIdx !== -1) {
            const pageNum = Math.floor(itemIdx / state.itemPageSize) + 1;
            changeItemPage(pageNum);
            
            // Scroll to the row and briefly animate its background
            setTimeout(() => {
                const targetRow = document.getElementById(`item-row-${itemId}`);
                if (targetRow) {
                    targetRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    targetRow.style.backgroundColor = 'rgba(16, 185, 129, 0.25)';
                    setTimeout(() => {
                        targetRow.style.transition = 'background-color 1s ease';
                        targetRow.style.backgroundColor = '';
                    }, 2000);
                }
            }, 100);
        }
    }, 50);
}

// Lightbox Logic
function openLightbox(index) {
    if (!state.selectedStore || state.selectedStore.images.length === 0) return;
    
    state.currentImageIndex = index;
    const overlay = document.getElementById('lightbox-overlay');
    overlay.classList.add('active');
    
    resetZoom();
    updateLightboxImage();
}

function closeLightbox() {
    document.getElementById('lightbox-overlay').classList.remove('active');
}

function updateLightboxImage() {
    const store = state.selectedStore;
    if (!store || store.images.length === 0) return;
    
    const imgName = store.images[state.currentImageIndex];
    const img = document.getElementById('lightbox-img');
    
    // Show spinner or placeholder if needed, then update image src
    img.src = `menu_images/${imgName}`;
    
    // Page count text
    document.getElementById('lightbox-page-info').textContent = `Page ${state.currentImageIndex + 1} of ${store.images.length}`;
    
    // Toggle prev/next buttons
    const prevBtn = document.getElementById('lightbox-prev-btn');
    const nextBtn = document.getElementById('lightbox-next-btn');
    
    prevBtn.style.display = store.images.length > 1 ? 'block' : 'none';
    nextBtn.style.display = store.images.length > 1 ? 'block' : 'none';
}

function navigateLightbox(dir) {
    const store = state.selectedStore;
    if (!store) return;
    
    const count = store.images.length;
    if (count <= 1) return;
    
    state.currentImageIndex = (state.currentImageIndex + dir + count) % count;
    resetZoom();
    updateLightboxImage();
}

// Lightbox Zoom and Pan functions
function zoomLightbox(factor) {
    const prevScale = state.zoomScale;
    state.zoomScale = Math.max(0.5, Math.min(10, state.zoomScale * factor));
    
    // Adjust pan coordinates slightly to center zoom
    state.panX = state.panX * (state.zoomScale / prevScale);
    state.panY = state.panY * (state.zoomScale / prevScale);
    
    applyTransforms();
}

function resetZoom() {
    state.zoomScale = 1;
    state.panX = 0;
    state.panY = 0;
    applyTransforms();
}

function applyTransforms() {
    const imgContainer = document.getElementById('lightbox-img-container');
    imgContainer.style.transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.zoomScale})`;
}

// Mouse dragging/panning events
function startDrag(e) {
    state.isDragging = true;
    state.startX = e.clientX - state.panX;
    state.startY = e.clientY - state.panY;
    document.getElementById('lightbox-img-container').style.cursor = 'grabbing';
}

function drag(e) {
    if (!state.isDragging) return;
    state.panX = e.clientX - state.startX;
    state.panY = e.clientY - state.startY;
    applyTransforms();
}

function endDrag() {
    state.isDragging = false;
    document.getElementById('lightbox-img-container').style.cursor = 'grab';
}

// Highlight matching search query text utility
function highlightText(text, search) {
    if (!search) return escapeHTML(text);
    
    const str = String(text);
    const regex = new RegExp(`(${escapeRegExp(search)})`, 'gi');
    return escapeHTML(str).replace(regex, '<span class="highlight">$1</span>');
}

// Escape regexp search patterns
function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\\\\\\]\\\\/]/g, '\\\\$&');
}

// Escape HTML utility to prevent XSS issues with loaded data
function escapeHTML(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
"""
    
    # Save frontend files
    print(f"Writing index.html...")
    with open(os.path.join(dest_dir, "index.html"), 'w', encoding='utf-8') as f:
        f.write(html_content)
        
    print(f"Writing style.css...")
    with open(os.path.join(dest_dir, "style.css"), 'w', encoding='utf-8') as f:
        f.write(css_content)
        
    print(f"Writing app.js...")
    with open(os.path.join(dest_dir, "app.js"), 'w', encoding='utf-8') as f:
        f.write(app_content)
        
    print("Frontend files written successfully.")
    print(f"COMPLETE: Visual Database created at '{dest_dir}'.")
    print(f"Open '{os.path.join(dest_dir, 'index.html')}' in a browser to inspect.")

if __name__ == "__main__":
    build_database()
