import React from 'react';
import { DollarSign } from 'lucide-react';

const CostPill = ({ cost }) => {
  return (
    <div className="bg-border/30 px-3 py-1 rounded-full flex items-center space-x-2 border border-border">
      <DollarSign className="w-3.5 h-3.5 text-success" />
      <span className="text-xs font-mono font-medium">${typeof cost === 'number' ? cost.toFixed(2) : cost}</span>
    </div>
  );
};

export default CostPill;
