import withPWA from "next-pwa";
import runtimeCaching from "next-pwa/cache.js";

/** @type {import('next').NextConfig} */
const nextConfig = {
  async headers() {
    return [
      {
        source: "/download/:path*",
        headers: [
          { key: "Cache-Control", value: "no-store" },
        ],
      },
      {
        source: "/download/Blagajna.appinstaller",
        headers: [
          { key: "Content-Type", value: "application/appinstaller" },
          { key: "Cache-Control", value: "no-store" },
        ],
      },
      {
        source: "/download/:file*.msix",
        headers: [
          { key: "Content-Type", value: "application/msix" },
          { key: "Cache-Control", value: "no-store" },
        ],
      },
      {
        source: "/download/:file*.cer",
        headers: [
          { key: "Content-Type", value: "application/pkix-cert" },
          { key: "Cache-Control", value: "no-store" },
        ],
      },
    ];
  },
};

const pwaConfig = {
  dest: "public",
  disable: process.env.NODE_ENV === "development",
  cleanupOutdatedCaches: true,
  clientsClaim: true,
  skipWaiting: true,
  runtimeCaching: [
    {
      urlPattern: new RegExp("^/_next/.*", "i"),
      handler: "NetworkFirst",
      options: {
        cacheName: "next-assets",
        networkTimeoutSeconds: 10,
        expiration: {
          maxEntries: 50,
          maxAgeSeconds: 60,
        },
      },
    },
    {
      urlPattern: new RegExp("^/api/.*", "i"),
      handler: "NetworkFirst",
      method: "GET",
      options: {
        cacheName: "api-cache",
        networkTimeoutSeconds: 10,
        expiration: {
          maxEntries: 50,
          maxAgeSeconds: 300,
        },
      },
    },
    ...runtimeCaching,
  ],
};

export default withPWA(pwaConfig)(nextConfig);
