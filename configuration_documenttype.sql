--
-- PostgreSQL database dump
--

-- Dumped from database version 16.4 (Debian 16.4-1.pgdg110+2)
-- Dumped by pg_dump version 16.4 (Debian 16.4-1.pgdg110+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: configuration_documenttype; Type: TABLE DATA; Schema: public; Owner: postgis
--

INSERT INTO public.configuration_documenttype VALUES (1, 'Primka', 'PRIMKA', 'in', 'Ulaz robe - primka', 0, true, 2, 1, 1, 576, 824, 647, 157, 1852, 1801);
INSERT INTO public.configuration_documenttype VALUES (2, 'Racun', 'RACUN', 'out', '', 0, true, NULL, NULL, 1, 485, NULL, 947, NULL, 1852, NULL);
INSERT INTO public.configuration_documenttype VALUES (3, 'Ulazni racun', 'UR', 'in', '', 0, true, NULL, NULL, 1, NULL, NULL, NULL, 603, NULL, 1284);


--
-- Name: configuration_documenttype_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgis
--

SELECT pg_catalog.setval('public.configuration_documenttype_id_seq', 3, true);


--
-- PostgreSQL database dump complete
--

