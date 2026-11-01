const nextConfig = {
  images: { unoptimized: true },

  async redirects() {
    return [
      {
        source: "/:path*",
        has: [
          {
            type: "host",
            value: "www.masar.wiki",
          },
        ],
        destination: "https://masar.wiki/:path*",
        permanent: true,
      },
    ];
  },
};

module.exports = nextConfig;
