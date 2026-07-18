SET search_path = imdb;

SELECT
    g.name AS genre,
    ci.role_type,
    count(*) AS cast_rows,
    count(DISTINCT ci.person_id) AS people,
    round(avg(t.runtime_minutes), 1) AS avg_runtime
FROM genre g
JOIN title t ON t.genre_id = g.id
JOIN cast_info ci ON ci.title_id = t.id
WHERE t.rating >= 7.0
GROUP BY g.id, g.name, ci.role_type
ORDER BY cast_rows DESC;
