import React, { useState, useEffect } from 'react';
import SearchBar from './components/SearchBar';
import FoodGrid from './components/FoodGrid';
import ItemModal from './components/ItemModal';
import { Database } from 'lucide-react';

const API = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';

function App() {
  const [stats, setStats] = useState({ total_items: 0, status: 'connecting...' });
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedItem, setSelectedItem] = useState(null);

  const fetchStats = async () => {
    try {
      const res = await fetch(`${API}/`);
      const data = await res.json();
      setStats(data);
    } catch (err) {
      console.error(err);
      setStats({ total_items: 0, status: 'offline' });
    }
  };

  const searchItems = async (query = '') => {
    setLoading(true);
    try {
      const url = query
        ? `${API}/items?query=${encodeURIComponent(query)}&page=1&size=50`
        : `${API}/items?page=1&size=50`;
        
      const res = await fetch(url);
      const data = await res.json();
      setItems(data.items || []);
    } catch (err) {
      console.error(err);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchStats();
    searchItems();
    
    // Poll stats every 5 seconds to show realtime ingest progress if any
    const interval = setInterval(fetchStats, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="app-container">
      <header style={{ textAlign: 'center', marginBottom: '3rem' }}>
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
          <Database size={40} color="var(--accent-cyan)" />
          <h1>Global Food Database</h1>
        </div>
        <p className="subtitle">
          Exploring 
          <strong style={{ color: 'var(--text-main)', margin: '0 0.5rem', fontSize: '1.4rem' }}>
            {stats.total_items.toLocaleString()}
          </strong> 
          items in real-time
        </p>
      </header>

      <main>
        <SearchBar onSearch={searchItems} />
        <FoodGrid items={items} onCardClick={setSelectedItem} loading={loading} />
      </main>

      {selectedItem && (
        <ItemModal item={selectedItem} onClose={() => setSelectedItem(null)} />
      )}
    </div>
  );
}

export default App;
