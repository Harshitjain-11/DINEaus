# chatbot/utils.py
from itertools import count

# start orders at 1000
_order_counter = count(1000)

def next_order_id():
    return int(next(_order_counter))
