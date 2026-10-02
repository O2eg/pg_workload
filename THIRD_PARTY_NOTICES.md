# Third-party notices

## Pagila

The packaged `pagila` profile includes a modified copy of the Pagila schema
from <https://github.com/devrimgunduz/pagila>. Pagila's data dump is not
distributed in the source repository or Python package. The profile uses an
original local generator to create synthetic rows and requires no upstream data.

Copyright (c) Devrim Gündüz <devrim@gunduz.org>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Synthetic movie-domain workload

The bundled `imdb` profile includes SQL query shapes migrated and adapted from
the predecessor `pg_workload_generator` implementation. Its data generator is
local and deterministic. No source IMDB dataset, CSV archive, or downloaded row
data is included in the source distribution or wheel.

## pg_perf_bench profile sources

The Pagila and IMDb schemas, load plans, index/constraint definitions and workload SQL
are adapted from `pg_perf_bench` v0.6.1, commit
`5eec23ce4c0edf3001bdbdb70339406221a3c903`, <https://github.com/O2eg/pg_perf_bench>.
The psql loader and scheduled-run adaptations are maintained in pg_workload.

MIT License

Copyright (c) 2023 Tantor Labs

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
