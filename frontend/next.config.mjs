import withPWA from "next-pwa";
import runtimeCaching from "next-pwa/cache.js";

/** @type {import('next').NextConfig} */
const nextConfig = {
  async headers() {
    return [
      {
        source: "/",
        headers: [
          { key: "Cache-Control", value: "no-store, no-cache, must-revalidate" },
        ],
      },
      {
        source: "/login",
        headers: [
          { key: "Cache-Control", value: "no-store, no-cache, must-revalidate" },
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
        source: "/download/:file*.appinstaller",
        headers: [
          { key: "Content-Type", value: "application/appinstaller" },
          { key: "Cache-Control", value: "no-store" },
        ],
      },
      {
        source: "/download/:file*.msix",
        headers: [
          { key: "Content-Type", value: "application/msix" },
          { key: "Cache-Control", value: "public, max-age=31536000, immutable" },
        ],
      },
      {
        source: "/download/:file*.msixbundle",
        headers: [
          { key: "Content-Type", value: "application/msixbundle" },
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
      {
        source: "/download/:file*.ps1",
        headers: [
          { key: "Content-Type", value: "text/plain; charset=utf-8" },
          { key: "Cache-Control", value: "no-store" },
        ],
      },
      {
        source: "/download/RunDesk.Client.appinstaller",
        headers: [
          { key: "Content-Type", value: "application/xml" },
          { key: "Cache-Control", value: "no-store, no-cache, must-revalidate" },
        ],
      },
      {
        source: "/download/RunDesk.Client_1.4.7.0_x64.msix",
        headers: [
          { key: "Content-Type", value: "application/msix" },
          { key: "Cache-Control", value: "public, max-age=31536000, immutable" },
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
