import React from 'react';
import { render, act } from '@testing-library/react';
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

// Let every already-resolved mock promise and the renders it causes run to the end. Mocked API calls resolve on
// microtasks, so this is deterministic and needs no clock: findBy*/waitFor poll on real timers (1 s limit) and fail
// on a loaded machine even though nothing is actually slow.
export const settle = async (rounds = 6) => { for (let i = 0; i < rounds; i += 1) await act(async () => {}); };
