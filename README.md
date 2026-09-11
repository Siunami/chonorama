# Chronorama

Explore Shanghai's Bund from 1865 to 2020 in a panoramic timeline.

Live at <https://chronorama.vercel.app>.

The viewer, 52 published panoramas, and generation tools are in
[chronorama](chronorama/README.md).

To preview the published site locally:

```sh
node chronorama/build.mjs
python3 -m http.server 8747 --directory chronorama/dist
```

Open <http://localhost:8747>. Drag to look around, scroll to zoom, and use the
timeline or arrow keys to travel through the years.
