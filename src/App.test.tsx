import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import App from './App';

vi.mock('@/services/auth', () => ({
  isAuthenticated: () => true,
  getProfile: vi.fn().mockResolvedValue({ id: 'u1', username: 'test', email: 'test@example.com' }),
  getAvatarUrl: vi.fn().mockReturnValue('/avatar.png'),
}));

vi.mock('@/pages/Dashboard', () => ({
  default: () => <div data-testid="dashboard-page">Dashboard</div>,
}));

vi.mock('@/pages/NoteDetail', () => ({
  default: () => <div data-testid="note-detail-page">NoteDetail</div>,
}));

vi.mock('@/pages/pad', () => ({
  default: () => <div data-testid="pad-page">Pad</div>,
}));

vi.mock('@/pages/Login', () => ({
  default: () => <div data-testid="login-page">Login</div>,
}));

vi.mock('@/pages/SharePage', () => ({
  default: () => <div data-testid="share-page">Share</div>,
}));

vi.mock('@/pages/Profile', () => ({
  default: () => <div data-testid="profile-page">Profile</div>,
}));

vi.mock('@/pages/ChapterList', () => ({
  default: () => <div data-testid="chapter-list-page">ChapterList</div>,
}));

function setWindowPath(path: string) {
  const href = `http://localhost:5173${path}`;
  Object.defineProperty(window, 'location', {
    writable: true,
    value: {
      href,
      origin: 'http://localhost:5173',
      protocol: 'http:',
      hostname: 'localhost',
      port: '5173',
      pathname: path,
    },
  });
}

function resetWindowPath() {
  Object.defineProperty(window, 'location', {
    writable: true,
    value: {
      href: 'http://localhost:5173/',
      origin: 'http://localhost:5173',
      protocol: 'http:',
      hostname: 'localhost',
      port: '5173',
      pathname: '/',
    },
  });
}

describe('App routing', () => {
  afterEach(() => {
    resetWindowPath();
  });
  it('renders the Pad page on /subject/:id/session/:sessionId/pad', async () => {
    setWindowPath('/subject/nb1/session/s1/pad');
    const { getByTestId } = render(<App />);
    await waitFor(() => expect(getByTestId('pad-page')).toBeInTheDocument());
  });

  it('renders the note detail page on /subject/:id/session/:sessionId', async () => {
    setWindowPath('/subject/nb1/session/s1');
    const { getByTestId } = render(<App />);
    await waitFor(() => expect(getByTestId('note-detail-page')).toBeInTheDocument());
  });
});
