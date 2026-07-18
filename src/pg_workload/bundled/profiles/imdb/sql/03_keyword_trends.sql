SET search_path = imdb;

SELECT
    (t.production_year / 5) * 5 AS five_year_bucket,
    k.keyword,
    count(*) AS uses,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY t.rating) AS median_rating
FROM title t
JOIN movie_keyword mk ON mk.title_id = t.id
JOIN keyword k ON k.id = mk.keyword_id
WHERE t.production_year >= 1980
GROUP BY five_year_bucket, k.id, k.keyword
ORDER BY uses DESC
LIMIT 100;
