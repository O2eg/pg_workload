SET search_path = imdb;

SELECT
    (t.production_year / 5) * 5 AS five_year_bucket,
    k.keyword,
    count(*) AS uses,
    count(DISTINCT t.kind_id) AS represented_kinds
FROM title AS t
JOIN movie_keyword AS mk ON mk.movie_id = t.id
JOIN keyword AS k ON k.id = mk.keyword_id
WHERE t.production_year >= 1980
GROUP BY five_year_bucket, k.id, k.keyword
ORDER BY uses DESC
LIMIT 100;
