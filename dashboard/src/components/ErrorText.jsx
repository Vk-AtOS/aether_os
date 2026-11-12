import React from 'react';
import { Link } from 'react-router-dom';

// Renders an error that is either a plain string or {message, upgradeUrl} from apiErrorState().
const ErrorText = ({ error }) => {
  if (!error) return null;
  if (typeof error === 'string') return <>{error}</>;
  return (
    <>
      {error.message}
      {error.upgradeUrl && (
        <> <Link to={error.upgradeUrl} className="underline font-bold">See plans</Link></>
      )}
    </>
  );
};

export default ErrorText;
