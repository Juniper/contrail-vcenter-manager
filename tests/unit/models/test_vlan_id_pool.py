def test_reserve(vlan_id_pool):
    vlan_id_pool.reserve(0)

    assert vlan_id_pool.is_available(0) is False


def test_reserve_existing(vlan_id_pool):
    vlan_id_pool.reserve(0)
    vlan_id_pool.reserve(0)

    assert vlan_id_pool.is_available(0) is False


def test_get_first_available(vlan_id_pool):
    vlan_id_pool.reserve(0)

    result = vlan_id_pool.get_available()

    assert result == 1
    assert vlan_id_pool.is_available(1) is False


def test_no_available(vlan_id_pool):
    for i in xrange(4096):
        vlan_id_pool.reserve(i)

    result = vlan_id_pool.get_available()

    assert result is None


def test_free(vlan_id_pool):
    vlan_id_pool.reserve(0)

    vlan_id_pool.free(0)

    assert vlan_id_pool.is_available(0) is True


def test_free_and_get(vlan_id_pool):
    vlan_id_pool.reserve(0)

    vlan_id_pool.free(0)
    next_id = vlan_id_pool.get_available()

    assert next_id == 1


def test_excluede_vlans(vlan_id_pool):
    vlan_id_pool.reserve(0)

    next_id = vlan_id_pool.get_available(exclude=[1])

    assert next_id == 2


def test_free_repetitions(vlan_id_pool):
    vlan_id_pool.free(10)
    vlan_id_pool.reserve(10)

    assert vlan_id_pool.is_available(10) is False
