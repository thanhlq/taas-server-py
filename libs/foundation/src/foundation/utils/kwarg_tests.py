



def f1(a, b=1, c=2, **kwargs):
    print(f"a={a}, b={b}, c={c}")
    print(f"kwargs={kwargs}")


f1(10, c=5, b=20, d=30, e=40)  # a=10, b=20, c=2, kwargs={'d': 30, 'e': 40}
