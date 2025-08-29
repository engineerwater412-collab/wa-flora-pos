import React, { useState } from 'react';
import { Search, Loader, AlertCircle, Image } from 'lucide-react';

const ProductPriceSearch = () => {
  const [barcode, setBarcode] = useState('');
  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searched, setSearched] = useState(false);

  // Function to handle the barcode search
  const handleSearch = async () => {
    if (!barcode.trim()) {
      setError('Please enter a barcode');
      return;
    }

    setLoading(true);
    setError(null);
    setSearched(true);

    // Assuming the backend is running at http://127.0.0.1:5000
    const API_URL = 'http://127.0.0.1:5000/api/product_price';

    try {
      const response = await fetch(`${API_URL}?barcode=${encodeURIComponent(barcode)}`);
      
      if (!response.ok) {
        // Handle HTTP errors
        throw new Error('Product not found or network error');
      }
      
      const data = await response.json();
      
      setProduct({
        name: data.name,
        price: data.price,
        image_url: data.image_url || 'https://placehold.co/150x150?text=No+Image',
        stock: data.stock_level
      });
      setLoading(false);
    } catch (error) {
      setError(error.message);
      setLoading(false);
      setProduct(null);
    }
  };

  // Handle Enter key press
  const handleKeyPress = (e) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-6 bg-white rounded-xl shadow-lg">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Product Price Search</h1>
      
      <div className="flex gap-2 mb-6">
        <div className="flex-1 relative">
          <input
            type="text"
            value={barcode}
            onChange={(e) => setBarcode(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Enter Barcode or Scan"
            className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-lg"
            autoFocus
          />
          <Search className="absolute right-3 top-3.5 text-gray-400" size={20} />
        </div>
        <button 
          onClick={handleSearch}
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white px-6 py-3 rounded-lg font-medium transition-colors flex items-center gap-2"
        >
          {loading ? <Loader className="animate-spin" size={20} /> : 'Search'}
        </button>
      </div>

      {loading && (
        <div className="flex items-center justify-center p-8">
          <Loader className="animate-spin text-blue-600 mr-3" size={24} />
          <span className="text-lg text-gray-600">Searching for product...</span>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
          <div className="flex items-center">
            <AlertCircle className="text-red-600 mr-2" size={20} />
            <span className="text-red-800 font-medium">{error}</span>
          </div>
        </div>
      )}

      {searched && !loading && !product && !error && (
        <div className="text-center py-8 text-gray-500">
          <Search size={48} className="mx-auto mb-4 opacity-50" />
          <p>Enter a barcode to search for a product</p>
        </div>
      )}

      {product && (
        <div className="bg-gray-50 rounded-lg p-6 animate-fade-in">
          <div className="flex flex-col md:flex-row gap-6">
            <div className="md:w-1/3 flex justify-center">
              <div className="relative">
                <img 
                  src={product.image_url} 
                  alt={product.name} 
                  className="w-40 h-40 object-cover rounded-lg shadow-md"
                  onError={(e) => {
                    e.target.src = 'https://placehold.co/150x150?text=No+Image';
                  }}
                />
                {product.stock <= 10 && (
                  <div className="absolute -top-2 -right-2 bg-red-500 text-white text-xs font-bold px-2 py-1 rounded-full">
                    Low Stock
                  </div>
                )}
              </div>
            </div>
            
            <div className="md:w-2/3">
              <h2 className="text-2xl font-bold text-gray-800 mb-2">{product.name}</h2>
              
              <div className="space-y-3">
                <div className="flex items-center">
                  <span className="text-3xl font-bold text-green-600">
                    KSh {product.price.toFixed(2)}
                  </span>
                </div>
                
                <div className="flex items-center text-gray-600">
                  <span className="font-medium">Stock Level:</span>
                  <span className={`ml-2 px-3 py-1 rounded-full text-sm font-medium ${
                    product.stock === 0 ? 'bg-red-100 text-red-800' :
                    product.stock <= 10 ? 'bg-yellow-100 text-yellow-800' :
                    'bg-green-100 text-green-800'
                  }`}>
                    {product.stock} {product.stock === 1 ? 'unit' : 'units'} available
                  </span>
                </div>
                
                <div className="pt-4 border-t border-gray-200">
                  <button className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-lg font-medium transition-colors">
                    Add to Cart
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProductPriceSearch;
