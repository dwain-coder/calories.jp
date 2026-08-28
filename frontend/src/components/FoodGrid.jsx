import React from 'react';
import FoodCard from './FoodCard';

const FoodGrid = ({ items, onCardClick, loading }) => {
  if (loading && items.length === 0) {
    return (
      <div className="loader-container">
        <div className="spinner"></div>
      </div>
    );
  }

  if (!loading && items.length === 0) {
    return (
      <div style={{ textAlign: 'center', color: 'var(--text-muted)', marginTop: '4rem' }}>
        <h2>No items found in the database.</h2>
        <p>Try a different search query.</p>
      </div>
    );
  }

  return (
    <div className="food-grid">
      {items.map((item) => (
        <FoodCard key={`${item.source}-${item.id}`} item={item} onClick={onCardClick} />
      ))}
    </div>
  );
};

export default FoodGrid;
