from homeloop_bench.gen.ko import final, josa


def test_josa_final_consonant():
    assert josa("우유", "을") == "우유를"
    assert josa("수건", "을") == "수건을"
    assert josa("책", "이") == "책이"
    assert josa("라이터", "이") == "라이터가"
    assert josa("사과", "과") == "사과와"
    assert josa("빵", "와") == "빵과"
    assert josa("머그컵", "이랑") == "머그컵이랑"
    assert josa("바나나", "이랑") == "바나나랑"


def test_josa_euro_ro_and_rieul():
    assert josa("책장", "으로") == "책장으로"
    assert josa("소파", "으로") == "소파로"
    assert josa("서울", "으로") == "서울로"          # final ㄹ takes 로


def test_latin_and_digits():
    assert final("TV") == "v"
    assert josa("B 방", "이") == "B 방이"
    assert final("10") == "c"
