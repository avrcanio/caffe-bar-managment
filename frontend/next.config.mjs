import withPWA from "next-pwa";
import runtimeCaching from "next-pwa/cache.js";

/** @type {import('next').NextConfig} */
const nextConfig = {};

const pwaConfig = {
  dest: "public",
  disable: process.env.NODE_ENV === "development",
  runtimeCaching: [
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
