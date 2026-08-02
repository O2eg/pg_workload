SET search_path = imdb;

SELECT
    mi.info AS genre,
    rt.role,
    count(*) AS cast_rows,
    count(DISTINCT ci.person_id) AS people,
    count(DISTINCT ci.movie_id) AS titles
FROM movie_info AS mi
JOIN info_type AS it ON it.id = mi.info_type_id AND it.info = 'genres'
JOIN cast_info AS ci ON ci.movie_id = mi.movie_id
JOIN role_type AS rt ON rt.id = ci.role_id
GROUP BY mi.info, rt.id, rt.role
ORDER BY cast_rows DESC;
