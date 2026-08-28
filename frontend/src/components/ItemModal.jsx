import React, { useEffect, useState } from 'react';
import { X, ExternalLink } from 'lucide-react';

const API = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';

const MacroRow = ({ label, value, unit, color }) => {
  // Rough percentage calculations based on standard daily values for visual flair
  const maxValues = { energy: 2000, protein: 50, fat: 65, carbs: 300 };
  const max = maxValues[label.toLowerCase()] || 100;
  const pct = value ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  
  return (
    <div className="macro-row">
      <div className="macro-label">{label}</div>
      <div className="macro-bar-container">
        <div 
          className="macro-bar" 
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <div className="macro-value">{value ? `${value}${unit}` : '-'}</div>
    </div>
  );
};

const fmt = (n) => {
  if (n == null) return '-';
  return Number.isInteger(n) ? String(n) : parseFloat(n.toFixed(2)).toString();
};

const NutrientProfile = ({ nutrients }) => (
  <div className="detail-section">
    <h3>Full Nutrient Profile ({nutrients.length})</h3>
    <div className="nutrient-grid">
      {nutrients.map((n, i) => (
        <div className="nutrient-item" key={`${n.code}-${i}`} title={n.code}>
          <span className="n-name">{n.name || n.code}</span>
          <span className="n-value">{fmt(n.amount)} {n.unit || ''}</span>
        </div>
      ))}
    </div>
  </div>
);

const RegionalDishSection = ({ dish }) => {
  const ingredients = (dish.recipe_ingredients || '')
    .split('\n').filter(Boolean)
    .map((line) => {
      const [name, qty] = line.split('\t');
      return { name, qty: qty || '' };
    });
  const steps = (dish.recipe_steps || '')
    .split('\n').filter(Boolean)
    .map((line) => line.replace(/^\s*\d+\.\s*/, ''));

  const Field = ({ label, value }) =>
    value ? (
      <div className="dish-field">
        <h4>{label}</h4>
        <p>{value}</p>
      </div>
    ) : null;

  return (
    <div className="detail-section">
      <h3>Regional Dish {dish.region ? `· ${dish.region}` : ''}</h3>
      <Field label="主な使用食材 · Main ingredients" value={dish.main_ingredients} />
      <Field label="歴史・由来 · History & origin" value={dish.history} />
      <Field label="食習の機会や時季 · When it's eaten" value={dish.occasion} />
      <Field label="飲食方法 · How it's eaten" value={dish.how_to_eat} />
      <Field label="保存・継承の取組 · Preservation" value={dish.preservation} />

      {ingredients.length > 0 && (
        <div className="dish-field">
          <h4>材料 · Ingredients</h4>
          <ul className="dish-ingredients">
            {ingredients.map((ing, i) => (
              <li key={i}><span>{ing.name}</span><span className="qty">{ing.qty}</span></li>
            ))}
          </ul>
        </div>
      )}

      {steps.length > 0 && (
        <div className="dish-field">
          <h4>作り方 · Recipe</h4>
          <ol className="dish-steps">
            {steps.map((step, i) => (
              <li key={i}><span className="step-num">{i + 1}</span><span>{step}</span></li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
};

const ItemModal = ({ item, onClose }) => {
  const [details, setDetails] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/items/${item.id}`)
      .then(res => res.json())
      .then(data => {
        setDetails(data);
        setLoading(false);
      })
      .catch(err => {
        console.error(err);
        setLoading(false);
      });
  }, [item]);

  // "No data" only when nothing is available across ALL sections, not just macros.
  const hasData = details && (
    details.nutrition ||
    details.nutrients?.length ||
    details.regional_dish ||
    details.ingredients?.ingredients_text ||
    details.shelf_life?.length ||
    details.barcodes?.length
  );

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content glass glass-panel" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2 className="modal-title">{item.name}</h2>
            <span className="pill pill-default" style={{marginRight: '0.5rem'}}>{item.source}</span>
            <span style={{ color: 'var(--text-muted)' }}>{item.category || 'General'}</span>
          </div>
          <button className="close-btn" onClick={onClose}>
            <X size={28} />
          </button>
        </div>

        {loading ? (
          <div className="loader-container"><div className="spinner"></div></div>
        ) : details ? (
          <div className="modal-body">
            
            {details.barcodes && details.barcodes.length > 0 && (
              <div className="detail-section" style={{ marginTop: 0 }}>
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                  {details.barcodes.map(b => (
                    <span key={b} className="pill" style={{ background: 'hsla(0,0%,100%,0.05)', border: '1px solid hsla(0,0%,100%,0.1)'}}>
                      UPC: {b}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {details.regional_dish && (
              <RegionalDishSection dish={details.regional_dish} />
            )}

            {details.nutrition && (
              <div className="detail-section">
                <h3>Nutrition Facts (per 100g/ml)</h3>
                <MacroRow label="Energy" value={details.nutrition.energy_kcal} unit="kcal" color="linear-gradient(90deg, #f59e0b, #ef4444)" />
                <MacroRow label="Protein" value={details.nutrition.protein_g} unit="g" color="linear-gradient(90deg, #8b5cf6, #d946ef)" />
                <MacroRow label="Fat" value={details.nutrition.fat_g} unit="g" color="linear-gradient(90deg, #06b6d4, #3b82f6)" />
                <MacroRow label="Carbs" value={details.nutrition.carbs_g} unit="g" color="linear-gradient(90deg, #10b981, #059669)" />
              </div>
            )}

            {details.jdi8 && (
              <div className="detail-section">
                <h3>Longevity Index (JDI8 Score: {details.jdi8.score}/8)</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.8rem', marginTop: '1rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    <div style={{ width: '100%', height: '12px', background: 'rgba(255,255,255,0.08)', borderRadius: '6px', overflow: 'hidden', position: 'relative', border: '1px solid var(--glass-border)' }}>
                      <div style={{ width: `${(details.jdi8.score / 8) * 100}%`, height: '100%', background: 'linear-gradient(90deg, var(--accent-cyan), #10b981)', borderRadius: '6px', transition: 'width 0.5s ease-out' }}></div>
                    </div>
                    <div style={{ fontWeight: '700', fontSize: '1.2rem', color: 'var(--accent-cyan)', whiteSpace: 'nowrap' }}>
                      {((details.jdi8.score / 8) * 100).toFixed(0)}%
                    </div>
                  </div>
                  <p style={{ fontSize: '0.9rem', color: 'var(--text-muted)', margin: 0, lineHeight: '1.4' }}>
                    Based on the Japanese Diet Index (JDI8) linked to lower mortality rates in clinical studies.
                  </p>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '0.6rem', marginTop: '0.5rem' }}>
                    {[
                      { label: 'Rice (米・ご飯)', active: details.jdi8.rice },
                      { label: 'Miso Soup (味噌汁)', active: details.jdi8.miso },
                      { label: 'Seaweeds (海藻類)', active: details.jdi8.seaweed },
                      { label: 'Pickles (漬物類)', active: details.jdi8.pickles },
                      { label: 'Green & Yellow Veg', active: details.jdi8.green_yellow_veg },
                      { label: 'Fish & Seafood', active: details.jdi8.fish },
                      { label: 'Green Tea (緑茶)', active: details.jdi8.green_tea },
                      { label: 'Low Meat (No Beef/Pork)', active: details.jdi8.low_meat }
                    ].map((comp, idx) => (
                      <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', color: comp.active ? 'var(--text-main)' : 'var(--text-muted)' }}>
                        <span style={{ color: comp.active ? '#10b981' : '#ef4444', fontWeight: 'bold' }}>
                          {comp.active ? '✓' : '✗'}
                        </span>
                        <span>{comp.label}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {details.nutrients && details.nutrients.length > 0 && (
              <NutrientProfile nutrients={details.nutrients} />
            )}

            {details.ingredients && details.ingredients.ingredients_text && (
              <div className="detail-section">
                <h3>Ingredients</h3>
                <p className="ingredients-text">{details.ingredients.ingredients_text}</p>
              </div>
            )}

            {!hasData && (
              <div className="detail-section" style={{ textAlign: 'center', padding: '2rem 0' }}>
                <p style={{ color: 'var(--text-muted)' }}>No detailed data available for this item.</p>
              </div>
            )}

            {details.shelf_life && details.shelf_life.length > 0 && (
              <div className="detail-section">
                <h3>Shelf Life & Storage</h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '1rem', marginTop: '1rem' }}>
                  {details.shelf_life.map((rule, idx) => (
                    <div key={idx} className="glass" style={{ padding: '1rem', borderRadius: '8px', border: '1px solid var(--glass-border)' }}>
                      <div style={{ fontWeight: '600', color: 'var(--text-main)', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        {rule.storage_method}
                      </div>
                      <div style={{ fontSize: '1.2rem', color: 'var(--accent-cyan)', marginBottom: '0.5rem' }}>
                        {rule.min_days === rule.max_days ? (
                          <span>{rule.min_days} days</span>
                        ) : (
                          <span>{rule.min_days} - {rule.max_days} days</span>
                        )}
                      </div>
                      {rule.tips && (
                        <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                          {rule.tips}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {details.source && (
              <div className="detail-section" style={{ borderTop: '1px solid var(--glass-border)', paddingTop: '1.5rem', marginTop: '2rem' }}>
                <span style={{ color: 'var(--text-muted)', marginRight: '0.5rem' }}>Source:</span>
                {details.source_url ? (
                  <a href={details.source_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-cyan)', display: 'inline-flex', alignItems: 'center', gap: '0.4rem', textDecoration: 'none' }}>
                    {details.source} <ExternalLink size={15} />
                  </a>
                ) : (
                  <span style={{ color: 'var(--text-main)' }}>{details.source}</span>
                )}

                {details.license && (
                  <div style={{ marginTop: '1rem', padding: '1rem', borderRadius: '8px', background: details.source === 'OpenFoodFacts' ? 'rgba(239, 68, 68, 0.08)' : 'rgba(16, 185, 129, 0.08)', border: `1px solid ${details.source === 'OpenFoodFacts' ? 'rgba(239, 68, 68, 0.2)' : 'rgba(16, 185, 129, 0.2)'}` }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                      <span style={{ fontSize: '0.75rem', background: details.source === 'OpenFoodFacts' ? '#ef4444' : '#10b981', color: '#fff', padding: '0.1rem 0.4rem', borderRadius: '4px', fontWeight: 'bold' }}>
                        {details.license}
                      </span>
                      <strong style={{ fontSize: '0.85rem', color: 'var(--text-main)' }}>
                        {details.source === 'OpenFoodFacts' ? 'Share-Alike Required' : 'Proprietary Use Safe'}
                      </strong>
                    </div>
                    {details.license_warning && (
                      <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: 0, marginTop: '0.25rem', lineHeight: '1.4' }}>
                        {details.license_warning}
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}

          </div>
        ) : (
          <p>Failed to load details.</p>
        )}
      </div>
    </div>
  );
};

export default ItemModal;
