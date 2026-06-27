import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Auto cleanup after each test
afterEach(() => {
  cleanup()
})

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => { store[key] = value },
    removeItem: (key: string) => { delete store[key] },
    clear: () => { store = {} },
  }
})()

Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
})

// Mock window.location
Object.defineProperty(window, 'location', {
  writable: true,
  value: {
    href: 'http://localhost:5173/',
    origin: 'http://localhost:5173',
    protocol: 'http:',
    hostname: 'localhost',
    port: '5173',
  },
})

// Mock fetch globally
global.fetch = vi.fn()

// Mock HTMLCanvasElement 2D context for jsdom (canvas drawing tests)
HTMLCanvasElement.prototype.getContext = vi.fn(function (this: HTMLCanvasElement, contextId: string) {
  if (contextId !== '2d') return null;
  return {
    canvas: this,
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    quadraticCurveTo: vi.fn(),
    stroke: vi.fn(),
    setTransform: vi.fn(),
    scale: vi.fn(),
  } as unknown as CanvasRenderingContext2D;
}) as typeof HTMLCanvasElement.prototype.getContext;

// Mock ResizeObserver for component tests that use it
class MockResizeObserver implements ResizeObserver {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}

global.ResizeObserver = MockResizeObserver;
