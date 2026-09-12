# Chronorama

Explore Shanghai's Bund from 1865 to 2020 in a panoramic timeline.

Live at <https://chronorama.vercel.app>.
The original six-image version is preserved for comparison at
<https://chronorama.vercel.app/v1>.

The viewer and generation tools are in
[chronorama](chronorama/README.md).

Image folders are local and ignored by Git. Before building a fresh checkout,
copy `chronorama/output/`, `chronorama/reference/`, and
`chronorama/versions/v1/output/` from an existing workspace, including their
manifests and alignment data.

To preview the site with those assets in place:

```sh
node chronorama/build.mjs
python3 -m http.server 8747 --directory chronorama/dist
```

Open <http://localhost:8747>. Drag to look around, scroll to zoom, and use the
timeline or arrow keys to travel through the years.
