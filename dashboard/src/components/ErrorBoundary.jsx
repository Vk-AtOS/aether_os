import React from 'react';
import { AlertTriangle } from 'lucide-react';

// Stateless wrapper — changing its key forces a full remount of children
const ChildMount = ({ children }) => children;

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, retryKey: 0 };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error('ErrorBoundary caught:', error, info);
  }

  handleRetry = () => {
    // Increment retryKey so ChildMount remounts with a new key, giving children a fresh instance
    this.setState(prev => ({ hasError: false, error: null, retryKey: prev.retryKey + 1 }));
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center min-h-[300px] p-8 text-center">
          <div className="bg-red-900/20 border border-red-600/40 rounded-xl p-8 max-w-lg w-full">
            <AlertTriangle className="w-10 h-10 text-red-400 mx-auto mb-4" />
            <h2 className="text-red-200 font-bold text-lg mb-2">Something went wrong</h2>
            <p className="text-red-400/80 text-sm mb-6 font-mono break-all">
              {this.state.error?.message || 'An unexpected error occurred'}
            </p>
            <button
              onClick={this.handleRetry}
              className="px-6 py-2 bg-red-700/50 hover:bg-red-700 text-white text-xs font-bold rounded-lg transition-colors border border-red-600/40"
            >
              RETRY
            </button>
          </div>
        </div>
      );
    }
    return <ChildMount key={this.state.retryKey}>{this.props.children}</ChildMount>;
  }
}

export default ErrorBoundary;
