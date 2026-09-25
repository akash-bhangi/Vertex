import type { NextConfig } from 'next';
import path from 'path';

const nextConfig: NextConfig = {
  outputFileTracingRoot: path.join(__dirname, '.'),
  output: 'standalone',
  devIndicators: false,
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: '**',
      },
    ],
  },
  env: {
    NEXT_PUBLIC_SUPABASE_URL:
      process.env.NEXT_PUBLIC_SUPABASE_URL ||
      process.env.SUPABASE_URL ||
      'https://heezkejugtehennmiugd.supabase.co',
    NEXT_PUBLIC_SUPABASE_ANON_KEY:
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
      process.env.SUPABASE_ANON_KEY ||
      'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhlZXprZWp1Z3RlaGVubm1pdWdkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgwNjgyMTYsImV4cCI6MjEwMzY0NDIxNn0.Ft0oe-ked_Eiba9LPOmWbc1LHvRgq9DnD27q9FPj6L8',
  },
  async rewrites() {
    const backendUrl = process.env.INTERNAL_BACKEND_URL || 'http://127.0.0.1:8000';
    return [
      {
        source: '/api/v1/:path*',
        destination: `${backendUrl}/api/v1/:path*`,
      },
      {
        source: '/docs',
        destination: `${backendUrl}/docs`,
      },
      {
        source: '/openapi.json',
        destination: `${backendUrl}/openapi.json`,
      },
    ];
  },
};

export default nextConfig;
