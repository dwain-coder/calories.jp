import React from 'react';

const FoodCard = ({ item, onClick }) => {
  const getSourceClass = (source) => {
    if (!source) return 'pill-default';
    const s = source.toLowerCase();
    if (s.includes('openfoodfacts')) return 'pill-openfoodfacts';
    if (s.includes('mext')) return 'pill-mext';
    if (s.includes('maff')) return 'pill-maff';
    if (s.includes('usda')) return 'pill-usda';
    return 'pill-default';
  };

  return (
    <div className="glass food-card" onClick={() => onClick(item)}>
      <span className={`pill ${getSourceClass(item.source)}`}>
        {item.source}
      </span>
      <h3 className="food-title">{item.name}</h3>

      {item.nutrition && (
        <div style={{ display: 'flex', gap: '0.8rem', flexWrap: 'wrap', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          {item.nutrition.energy_kcal != null && <span style={{ color: '#f59e0b' }}>{Math.round(item.nutrition.energy_kcal)} kcal</span>}
          {item.nutrition.protein_g != null && <span style={{ color: '#8b5cf6' }}>{Math.round(item.nutrition.protein_g)}g P</span>}
          {item.nutrition.fat_g != null && <span style={{ color: '#06b6d4' }}>{Math.round(item.nutrition.fat_g)}g F</span>}
          {item.nutrition.carbs_g != null && <span style={{ color: '#10b981' }}>{Math.round(item.nutrition.carbs_g)}g C</span>}
        </div>
      )}

      {item.nutrient_count > 4 && (
        <span className="nutrient-badge">{item.nutrient_count} nutrients</span>
      )}

      {item.main_ingredients && (
        <div className="card-hint">🍲 {item.main_ingredients}</div>
      )}

      <div style={{ marginTop: 'auto', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem', textTransform: 'capitalize' }}>
          {item.category || 'General'}
        </span>
      </div>
    </div>
  );
};

export default FoodCard;
