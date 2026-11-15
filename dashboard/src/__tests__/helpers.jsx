import React from 'react';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// Render a page inside a router. Pages call `api` from '../api'; tests mock that module per file.
export const renderAt = (ui, route = '/') => render(<MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>);

// An axios-like resolved response.
export const ok = (data) => Promise.resolve({ data });
// An axios-like rejection with a FastAPI detail.
export const fail = (status, detail) => {
  const p = Promise.reject({ response: { status, data: { detail } }, message: 'x' });
  p.catch(() => {}); // created before the code under test awaits it: not an unhandled rejection
  return p;
};
