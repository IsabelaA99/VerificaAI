import pytest

from utils.message_utils import MAX_MESSAGE_CHARS, as_link, normalize_command, shared_link, split_message


class TestSplitMessage:
    def test_texto_vazio_nao_gera_mensagem(self):
        assert split_message("") == []
        assert split_message("   \n\n  ") == []

    def test_texto_curto_vai_inteiro_em_uma_mensagem(self):
        assert split_message("Olá, tudo bem?") == ["Olá, tudo bem?"]

    def test_limite_exato_cabe_em_uma_mensagem_e_um_a_mais_gera_duas(self):
        assert len(split_message("a" * MAX_MESSAGE_CHARS)) == 1
        blocks = split_message("a" * (MAX_MESSAGE_CHARS + 1))
        assert [len(b) for b in blocks] == [MAX_MESSAGE_CHARS, 1]

    def test_corta_entre_secoes_e_nao_no_meio_de_uma_lista(self):
        first = "*Primeira*\n" + "\n".join(f"• item {i} " + "x" * 80 for i in range(9))
        second = "*Segunda*\n" + "\n".join(f"• item {i} " + "y" * 80 for i in range(9))
        blocks = split_message(f"{first}\n\n{second}", max_chars=len(first) + 10)
        assert blocks == [first, second]

    def test_junta_secoes_curtas_na_mesma_mensagem(self):
        assert split_message("A\n\nB\n\nC") == ["A\n\nB\n\nC"]

    def test_nunca_passa_do_limite_nem_devolve_bloco_vazio(self):
        text = "\n\n".join(["palavra " * 120, "x" * 4000, "linha curta", ("frase comprida " * 60 + "\n") * 5])
        blocks = split_message(text)
        assert blocks
        assert all(0 < len(block) <= MAX_MESSAGE_CHARS for block in blocks)

    def test_primeiro_paragrafo_maior_que_o_limite_nao_gera_bloco_vazio(self):
        # Caso que o split_message do RosaIA tratava mal: primeiro parágrafo já estoura o limite.
        blocks = split_message("a" * 2000 + "\n" + "fim", max_chars=1600)
        assert all(block for block in blocks)
        assert all(len(block) <= 1600 for block in blocks)

    def test_linha_gigante_sem_espaco_e_cortada_sem_perder_caracteres(self):
        blocks = split_message("x" * 3500)
        assert [len(b) for b in blocks] == [1600, 1600, 300]
        assert "".join(blocks) == "x" * 3500

    def test_linha_longa_com_espacos_e_cortada_entre_palavras(self):
        words = ["palavra"] * 500
        blocks = split_message(" ".join(words), max_chars=100)
        assert all(len(b) <= 100 for b in blocks)
        assert " ".join(blocks).split() == words

    def test_nao_perde_nem_inventa_conteudo(self):
        text = "\n\n".join(f"Parágrafo {i}: " + "texto " * 60 for i in range(30))
        blocks = split_message(text)
        assert " ".join(" ".join(blocks).split()) == " ".join(text.split())

    def test_aceita_quebra_de_linha_do_windows(self):
        assert split_message("A\r\n\r\nB") == ["A\n\nB"]

    def test_limite_invalido_e_recusado(self):
        with pytest.raises(ValueError):
            split_message("texto", max_chars=0)


class TestNormalizeCommand:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Olá!!", "ola"),
            ("  OI  ", "oi"),
            ("Bom dia 🙂", "bom dia"),
            ("Como funciona?", "como funciona"),
            ("AJUDA...", "ajuda"),
            ("Começar", "comecar"),
            ("👍", ""),
            ("???", ""),
        ],
    )
    def test_normaliza(self, raw, expected):
        assert normalize_command(raw) == expected


class TestAsLink:
    @pytest.mark.parametrize(
        "raw", ["https://exemplo.com/noticia", "http://exemplo.com", "  HTTPS://Exemplo.com/a?b=1#c  "]
    )
    def test_link_completo(self, raw):
        result = as_link(raw)
        assert result is not None
        assert result[1] is True

    @pytest.mark.parametrize("raw", ["exemplo.com", "www.exemplo.com/noticia", "g1.globo.com/politica/x.ghtml"])
    def test_endereco_sem_http_e_reconhecido_como_incompleto(self, raw):
        result = as_link(raw)
        assert result is not None
        assert result[1] is False

    @pytest.mark.parametrize(
        "raw",
        [
            "veja isso https://exemplo.com/noticia",
            "https://exemplo.com/a depois outro texto",
            "Isso aconteceu ontem.",
            "3.14",
            "",
            "   ",
        ],
    )
    def test_texto_comum_nao_e_link(self, raw):
        assert as_link(raw) is None


class TestSharedLink:
    @pytest.mark.parametrize(
        ("raw", "link"),
        [
            ("olha isso https://exemplo.com/a", "https://exemplo.com/a"),
            ("https://exemplo.com/a?b=1\n\nverdade?", "https://exemplo.com/a?b=1"),
            ("viu? (https://exemplo.com/a).", "https://exemplo.com/a"),
            ("“https://exemplo.com/a”", "https://exemplo.com/a"),
        ],
    )
    def test_link_com_comentario_curto(self, raw, link):
        assert shared_link(raw, max_comment_chars=50) == link

    def test_comentario_do_tamanho_do_minimo_ja_e_texto(self):
        assert shared_link("a" * 50 + " https://exemplo.com/a", max_comment_chars=50) is None
        assert shared_link("a" * 49 + " https://exemplo.com/a", max_comment_chars=50) == "https://exemplo.com/a"

    @pytest.mark.parametrize("raw", ["sem link nenhum", "https://a.com/x e https://b.com/y", "exemplo.com/a veja"])
    def test_sem_um_unico_link_com_http(self, raw):
        assert shared_link(raw, max_comment_chars=50) is None
