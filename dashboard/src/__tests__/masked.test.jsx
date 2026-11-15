// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { Masked } from '../components/hr/hrParts';

describe('Masked', () => {
  it('shows no character of the secret until revealed', () => {
    const { container, getByLabelText } = render(<Masked value="123456789" />);
    expect(container.textContent).toBe('••••••');
    fireEvent.click(getByLabelText('Show value'));
    expect(container.textContent).toBe('123456789');
  });
});
