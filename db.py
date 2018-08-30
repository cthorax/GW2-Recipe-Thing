
import pickle
import configparser
from collections import Counter

import records
import requests

config = configparser.ConfigParser()
config.read('config.ini')

karma_conversion = config['db_only']['karma_conversion']
verbose = config['all files'].getboolean('verbose')
db_url = config['all files']['db_url']
db = records.Database(db_url=db_url)


def api_query(payload, endpoint, default=None):

    if endpoint == 'recipes_output':
        url = "https://api.guildwars2.com/v2/recipes/search?output={}".format(payload)
    elif endpoint == 'recipes_input':
        url = "https://api.guildwars2.com/v2/recipes/search?input={}".format(payload)
    elif endpoint == 'recipe_details':
        url = "https://api.guildwars2.com/v2/recipes/{}".format(payload)
    elif endpoint == 'api_recipes':
        url = "https://api.guildwars2.com/v2/recipes?access_token={}".format(payload)
    elif endpoint == 'item_details':
        url = "https://api.guildwars2.com/v2/items/{}".format(payload)
    elif endpoint == 'item_pricing':
        url = "https://api.guildwars2.com/v2/commerce/prices/{}".format(payload)
    elif endpoint == 'multi_item':
        assert isinstance(payload, list)
        list_string = str(payload)[1:-1].replace(' ', '')    # strips '[' and ']' from str representation.
        url = "https://api.guildwars2.com/v2/items?ids={}".format(list_string)
    elif endpoint == 'multi_recipe':
        assert isinstance(payload, list)
        list_string = str(payload)[1:-1].replace(' ', '')    # strips '[' and ']' from str representation.
        url = "https://api.guildwars2.com/v2/recipes?ids={}".format(list_string)
    elif endpoint == 'multi_pricing':
        assert isinstance(payload, list)
        list_string = str(payload)[1:-1].replace(' ', '')    # strips '[' and ']' from str representation.
        url = "https://api.guildwars2.com/v2/commerce/prices?ids={}".format(list_string)

    else:
        assert False

    result = requests.get(url=url)
    try:
        result.raise_for_status()
        result_list_or_dict = result.json()
    except requests.exceptions.HTTPError:
        result_list_or_dict = default

    return result_list_or_dict


def init_items():
    if verbose:
        print('initialising items table')

    db.query(query='DROP TABLE IF EXISTS items;')
    db.query(query="""CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    name TEXT,
    vendor_cost INTEGER DEFAULT 1234567890,
    karma_cost REAL DEFAULT 999999999999.0,
    vendor_value INTEGER DEFAULT 0,
    bound INTEGER,
    tp_cost INTEGER DEFAULT 1234567890,
    tp_value INTEGER DEFAULT 0
);""")
    db.query(query="INSERT INTO ITEMS (id, vendor_cost, karma_cost, vendor_value, bound, tp_cost, tp_value) VALUES (0, 0, 0, 0, 0, 0, 0);")


def init_recipes():
    if verbose:
        print('initialising recipe table')

    db.query(query='DROP TABLE IF EXISTS recipes;')
    initialise = """CREATE TABLE recipes (
    game_id INTEGER NOT NULL,
    is_altered INTEGER,
    unique_id INTEGER PRIMARY KEY,
    needs_recipe INTEGER,
    output_item INTEGER NOT NULL,
    output_quantity INTEGER NOT NULL,
    component_string TEXT NOT NULL
);"""
    db.query(query=initialise)


def init_views():      # karma conversion is how much  karma is worth 1 coin
    if verbose:
        print('initialising views')

    db.query(query='DROP VIEW IF EXISTS pricing;')
    create_string = """CREATE VIEW pricing AS
SELECT tp_cost, vendor_cost, karma_cost,
    CASE WHEN tp_cost < vendor_cost AND tp_cost < karma_cost / {converter}
        THEN 'TP'
    CASE WHEN vendor_cost <= tp_cost AND vendor_cost <= karma_cost / {converter}
        THEN 'vendor'
    CASE WHEN karma_cost / {converter} < vendor_cost AND tp_cost >= karma_cost / {converter}
        THEN 'karma'
    ELSE 'none'
    END AS best_method,
    CASE WHEN tp_cost < vendor_cost AND tp_cost < karma_cost / {converter}
        THEN tp_cost
    CASE WHEN vendor_cost <= tp_cost AND vendor_cost <= karma_cost / {converter}
        THEN vendor_cost
    CASE WHEN karma_cost / {converter} < vendor_cost AND tp_cost >= karma_cost / {converter}
        THEN karma_cost
    ELSE 0
    END AS best_cost
FROM items
);""".format(converter=karma_conversion)
    db.query(query=query)


def populate_items(item_id_list=None):
    if item_id_list is None:
        item_id_list = api_query(payload='', endpoint='item_details')

    with_value_template = '{id}, "{name}", {value}, {bound}), ('
    without_value_template = '{id}, "{name}", {bound}), ('

    item_list_chunks = [item_id_list[x:x + 200] for x in range(0, len(item_id_list), 200)]      # 200 is max paging size per wiki on the api v2. this code stolen from stack exchange.
    for batch_number, chunk in enumerate(item_list_chunks):
        with_values_flag = False
        without_values_flag = False
        insert_string_with_value = "INSERT INTO items(id, name, vendor_value, bound) VALUES ("
        insert_string_without_value = "INSERT INTO items(id, name, bound) VALUES ("
        item_details_list = api_query(payload=chunk, endpoint='multi_item', default=[])
        for item_number, item_dict in enumerate(item_details_list):
            if verbose:
                print('\rpopulating items table - chunk {current_chunk} of {total_chunks} - item {current_item} of {total_items}'.format(
                    current_chunk=batch_number +1, total_chunks=len(item_list_chunks),
                    current_item=item_number +1, total_items=len(item_details_list)
                ), end='')  # zero index

            item_id = item_dict.get('id')
            item_name = item_dict.get('name').replace('"', "'")     # very irritating
            flags = item_dict.get('flags', [])

            if 'SoulbindOnAcquire' in flags or 'AccountBound' in flags:
                bound = 1
            else:
                bound = 0

            if 'NoSell' in flags:
                vendor_value = None
            else:
                vendor_value = item_dict.get('vendor_value', None)

            if vendor_value:
                with_values_flag = True
                insert_string_with_value = '{}{}'.format(insert_string_with_value, with_value_template.format(id=item_id, name=item_name, value=vendor_value, bound=bound))
            else:
                without_values_flag = True
                insert_string_without_value = '{}{}'.format(insert_string_without_value, without_value_template.format(id=item_id, name=item_name, bound=bound))

        if with_values_flag:
            insert_string_with_value = insert_string_with_value[:-3]
            db.query(query=insert_string_with_value.format(id=item_id, bound=bound))

        if without_values_flag:
            insert_string_without_value = insert_string_without_value[:-3]
            db.query(query=insert_string_without_value.format(id=item_id, value=vendor_value, bound=bound))
    if verbose:
        print(' - done.')

    db.query('VACUUM;')


def vendor_pricing(vendor_dict=None):
    # dict must be of the form item_id: vendor price.
    if verbose:
        print('adding vendor pricing')

    if vendor_dict is None:
        with open('D:\Python\STUFF I WROTE\GW2 Recipe Thing\\vendor_dict.pickle', 'rb') as itemlist_file:
            try:
                vendor_dict = pickle.load(file=itemlist_file)
            except FileNotFoundError:
                vendor_dict = {}

    update_cost_string = '''
    UPDATE items
    SET vendor_cost = {cost}
    WHERE id = {id};'''
    update_karma_string = '''
    UPDATE items
    SET karma_cost = {karma}
    WHERE id = {id};'''

    for item_id, costs in vendor_dict.items():
        vendor_cost = costs.get('vendor', None)
        karma_cost = costs.get('karma', None)
        if vendor_cost:
            db.query(query=update_cost_string.format(id=item_id, cost=vendor_cost))
        if karma_cost:
            db.query(query=update_karma_string.format(id=item_id, karma=karma_cost))

    db.query('VACUUM;')


def trading_post_pricing(item_list=None, verbose=False, db=records.Database(db_url='sqlite:///./gw2.db')):
    if item_list is None:
        #todo get rid of this kludge holy shit
        item_list = list(eval(db.query('SELECT id FROM items;').export('csv').replace('\r\n', ', ')[4:]))

    update_string ="UPDATE items SET tp_{type} = {cost} WHERE id = {id};"

    item_list_chunks = [item_list[x:x + 200] for x in range(0, len(item_list), 200)]      # 200 is max paging size per wiki on the api v2. this code stolen from stack exchange.
    for batch_number, chunk in enumerate(item_list_chunks):
        if verbose:
            print('\rupdating trading post pricing - chunk {current} of {total}'.format(current=batch_number+1, total=len(item_list_chunks)), end='')     # zero index

        pricing_dict_list = api_query(payload=chunk, endpoint='multi_pricing', default=[])

        for pricing_dict in pricing_dict_list:
            # you BUY instantly from sells and you SELL instantly to buys
            item_id = pricing_dict.get('id')
            sell_dict = pricing_dict.get('buys', None)
            buy_dict = pricing_dict.get('sells', None)

            if sell_dict:
                cost_to_sell = sell_dict['unit_price']
                db.query(query=update_string.format(type='value', cost=cost_to_sell, id=item_id))
            if buy_dict:
                cost_to_buy = buy_dict['unit_price']
                db.query(query=update_string.format(type='cost', cost=cost_to_buy, id=item_id))
    if verbose:
        print(' - done.')

    db.query('VACUUM;')


def populate_recipe_table(recipe_list=None):
    if recipe_list is None:
        recipe_list = api_query(payload='', endpoint='recipe_details')

    missed_recipes = recipe_list.copy()
    skip_recipes = []

    recipe_list_chunks = [recipe_list[x:x + 200] for x in range(0, len(recipe_list), 200)]      # 200 is max paging size per wiki on the api v2. this code stolen from stack exchange.
    for batch_number, chunk in enumerate(recipe_list_chunks):
        recipe_dict_list = api_query(payload=chunk, endpoint='multi_recipe')
        for recipe_number, recipe_dict in enumerate(recipe_dict_list):
            if verbose:
                print('\rpopulating recipe table - chunk {current_chunk} of {total_chunks} - recipe {current_recipe} of {total_recipes}'.format(
                    current_chunk=batch_number +1, total_chunks=len(recipe_list_chunks),
                    current_recipe=recipe_number +1, total_recipes=len(recipe_dict_list)
                ), end='')  # zero index

            insert_string = """INSERT INTO recipes(
    game_id, is_altered, unique_id, output_item, output_quantity, needs_recipe, component_string
) VALUES(
    {id}, 0, {unique_id}, {output_id}, {output_quantity}, {needs_recipe}, {component_string}
)"""

            recipe_id = recipe_dict.get('id')
            if recipe_id in skip_recipes:
                missed_recipes.remove(recipe_id)
                skip_recipes.remove(recipe_id)
                continue

            output_item_id = recipe_dict.get('output_item_id')
            recipes_to_skip = api_query(payload=output_item_id, endpoint='recipes_output')
            if recipes_to_skip:
                skip_recipes.extend(recipes_to_skip)

            output_quantity = recipe_dict.get('output_item_count')
            flags = recipe_dict.get('flags')
            if 'LearnedFromItem' in flags:
                needs_recipe = 1
            else:
                needs_recipe = 0

            unique_id = generate_unique_id(recipe_id=recipe_id, size=7)
            
            ingredients = Counter()
            for ingredient in recipe_dict.get('ingredients', []):
                item_id = ingredient['item_id']
                quantity = ingredient['count']
                ingredients[item_id] += quantity

            component_string = ''
            for ingredient_id, ingredient_quantity in ingredients.most_common():
                component_string += "{ingredient_code}-{count},".format(ingredient_code=int(ingredient_id, 36), count=ingredient_quantity)

            query_string = insert_string.format(
                id=recipe_id, output_id=output_item_id, output_quantity=output_quantity, unique_id=unique_id,
                needs_recipe=needs_recipe, component_string=component_string
            )

            db.query(query=query_string)
            missed_recipes.remove(recipe_id)
            if recipe_id in skip_recipes:
                skip_recipes.remove(recipe_id)
    if verbose:
        print(' - done.')

    db.query('VACUUM;')
    return missed_recipes


def alternate_recipes(debug=False):
    from math import gcd
    added_recipes = False

    component_recipe_dict_list = db.query("SELECT * FROM recipes ORDER BY is_altered ASC, game_id ASC;").as_dict()

    for component_recipe_number, component_recipe_dict in enumerate(component_recipe_dict_list):
        component_recipe_unique_id = component_recipe_dict.get('unique_id')
        component_output_item = component_recipe_dict.get('output_item')
        component_output_quantity = component_recipe_dict.get('output_quantity')
        for slot_number in range(slots):
            product_recipe_dict_list = db.query('SELECT * FROM recipes WHERE item{formatted_number} = {item_id} ORDER BY is_altered ASC, game_id ASC;'.format(formatted_number=str(slot_number).zfill(2), item_id=component_output_item)).as_dict()
            for product_recipe_number, product_recipe_dict in enumerate(product_recipe_dict_list):
                if verbose:
                    print(
                        '\radding alternate recipes - component recipe {component} of {max_components} - slot {slot} of {max_slot} - product recipe {product} of {max_products}'.format(
                            slot=slot_number, max_slot=slots,
                            component=component_recipe_number, max_components=len(component_recipe_dict_list),
                            product=product_recipe_number, max_products=len(product_recipe_dict_list),
                        ), end='')

                product_recipe_game_id = product_recipe_dict.get('game_id')
                product_recipe_needs_recipe = product_recipe_dict.get('needs_recipe')
                product_recipe_unique_id = product_recipe_dict.get('unique_id')
                product_recipe_output_item = product_recipe_dict.get('output_item')
                product_recipe_output_quantity = product_recipe_dict.get('output_quantity')
                combined_unique_id = generate_unique_id(product_recipe_unique_id, component_recipe_unique_id, size=7)
                dupecheck = db.query('SELECT * FROM recipes where unique_id = {}'.format(combined_unique_id)).as_dict()
                if dupecheck and not debug:
                    continue
                else:
                    insert_string = "INSERT INTO recipes (game_id, is_altered, needs_recipe, output_item, output_quantity, unique_id"
                    values_string = ") VALUES ({game_id}, {is_altered}, {needs_recipe}, {output_item}, {output_quantity}, {unique_id}"

                    for key, value in product_recipe_dict.items():
                        if key[:4] == 'item':
                            if value == component_output_item:
                                components_needed = product_recipe_dict['quantity{}'.format(key[-2:])]
                                break

                    discrepancy_gcd = gcd(component_output_quantity, components_needed)
                    required_discrepancy = components_needed // discrepancy_gcd
                    produced_discrepancy = component_output_quantity // discrepancy_gcd

                    combined_ingredients_counter = Counter()
                    for dictionary, discrepancy in zip([product_recipe_dict, component_recipe_dict], [produced_discrepancy, required_discrepancy]):
                        for inner_slot_number in range(slots):
                            temp_item = dictionary.get('item{}'.format(str(inner_slot_number).zfill(2)), None)
                            if temp_item:
                                if dictionary is product_recipe_dict and temp_item == component_output_item:
                                    continue
                                temp_quantity = dictionary['quantity{}'.format(str(inner_slot_number).zfill(2))] * discrepancy
                                combined_ingredients_counter[temp_item] += temp_quantity
                            else:
                                break

                    combined_recipe_dict = {
                        'game_id': product_recipe_game_id,
                        'is_altered': 1,
                        'output_item': product_recipe_output_item,
                        'needs_recipe': product_recipe_needs_recipe,
                        'output_quantity': product_recipe_output_quantity * produced_discrepancy,
                        'unique_id': combined_unique_id
                    }

                if len(combined_ingredients_counter.most_common()) > slots:
                    update_slots(len(combined_ingredients_counter.most_common()), db=db)

                for number, ingredient_tuple in enumerate(combined_ingredients_counter.most_common()):
                    temp_item, temp_quantity = ingredient_tuple
                    formatted_number = str(number).zfill(2)
                    combined_recipe_dict['item{number}'.format(number=formatted_number)] = temp_item
                    combined_recipe_dict['quantity{number}'.format(number=formatted_number)] = temp_quantity
                    insert_string += ', item{number}, quantity{number}'.format(number=formatted_number)
                    values_string += ', {{item{number}}}, {{quantity{number}}}'.format(number=formatted_number)

                values_string += ');'
                if dupecheck and debug:
                    # put collision testing here
                    if dupecheck[0] == combined_recipe_dict:
                        # same number of keys, same names for all keys, each key value matches.
                        pass
                    else:
                        pass
                else:
                    db.query(insert_string+values_string.format(**combined_recipe_dict))
                    added_recipes = True
                cleanup(verbose=verbose, db=db)

    return added_recipes


def get_price(recipe_id):
    select_string = "SELECT"
    revenue_string = " revenue"
    cost_template = " - {number}"
    as_string = " AS profit FROM pricing WHERE game_id = {recipe_id} ORDER BY profit LIMIT 1".format(recipe_id=recipe_id)
    for number in range(slots):
        bracketed_number = '{s' + str(number).zfill(2) + '}'
        select_string += " {},".format(bracketed_number)
        revenue_string += cost_template.format(number=bracketed_number)
    pricing_query = select_string + revenue_string + as_string

    unique_id_dict_list = db.query("SELECT unique_id FROM recipes WHERE game_id = {recipe_id}".format(recipe_id=recipe_id)).as_dict()
    best_profit = 0
    best_string = ''
    best_profit_dict = None

    for unique_id_dict in unique_id_dict_list:
        unique_id = unique_id_dict['unique_id']
        best_price_slot_dict_list = db.query("SELECT * FROM best_prices WHERE unique_id = {unique_id}".format(unique_id=unique_id)).as_dict()
        for best_price_slot_dict in best_price_slot_dict_list:
            query = pricing_query.format(**best_price_slot_dict)
            revenue_dict_list = db.query(query=query).as_dict()
            for revenue_dict in revenue_dict_list:
                profit = revenue_dict['profit']
                if profit:
                    if profit > best_profit:
                        best_profit = profit
                        best_string = unique_id
                        best_profit_dict = revenue_dict
                    else:
                        continue
                else:
                    continue

    if best_profit_dict:
        cleaned_profit_dict = {'cost_sum': 0, 'karma_sum': 0}
        for key, value in best_profit_dict.items():
            if value != 0 and value is not None:
                cleaned_profit_dict[key] = value
                if key[:-2] == 'cost' or key[:-2] == 'vendor':
                    cleaned_profit_dict['cost_sum'] += value
                elif key[:-2] == 'karma':
                    cleaned_profit_dict['karma_sum'] += value

        final_recipe_dict_list = db.query("SELECT * FROM final_recipe WHERE unique_id = {unique_id}".format(unique_id=best_string)).as_dict()
        for final_recipe_dict in final_recipe_dict_list:
            print("\nRECIPE ID:\t{game_id}\nCREATES:\t{output_quantity}x {output_name}\nINGREDIENTS:".format(**final_recipe_dict))
            for slot_key in cleaned_profit_dict.keys():
                type, number = slot_key[:-2], slot_key[-2:]
                if number == 'it' or number == 'um':
                    continue
                temp_name = final_recipe_dict['name{}'.format(number)]
                temp_quantity = final_recipe_dict['quantity{}'.format(number)]
                if type == 'cost':
                    item_price = '\tbuy item from TP for {} total'.format(format_prices(cleaned_profit_dict[slot_key]))
                elif type == 'vendor':
                    item_price = '\tbuy item from vendor for {} total'.format(format_prices(cleaned_profit_dict[slot_key]))
                elif type == 'karma':
                    item_price = '\tbuy item from vendor for {} karma total'.format(cleaned_profit_dict[slot_key])
                print('{quantity}x {name} - {cost}'.format(cost=item_price, name=temp_name, quantity=temp_quantity))
            if cleaned_profit_dict['cost_sum'] and cleaned_profit_dict['karma_sum']:
                print('TOTAL COST:\t\t{cost}, {karma} karma'.format(cost=format_prices(cleaned_profit_dict['cost_sum']), karma=cleaned_profit_dict['karma_sum']))
            elif cleaned_profit_dict['cost_sum']:
                print('TOTAL COST:\t\t{cost}'.format(cost=format_prices(cleaned_profit_dict['cost_sum'])))
            elif cleaned_profit_dict['karma_sum']:
                print('TOTAL COST:\t\t{karma} karma'.format(karma=cleaned_profit_dict['karma_sum']))
            print('TOTAL PROFIT:\t{profit}\n'.format(profit=format_prices(cleaned_profit_dict['profit'])))

    else:
        if verbose:
            print('no profitable version of recipe {game_id}'.format(game_id=recipe_id))


def format_prices(price):
    try:
        price = int(price)
        copper = price % 100
        silver = (price % 10000) // 100
        gold = price // 10000

        if gold:
            price_string = '{g}g {s}s {c}c'.format(g=gold, s=silver, c=copper)
        elif silver:
            price_string = '{s}s {c}c'.format(s=silver, c=copper)
        else:
            price_string = '{c}c'.format(c=copper)
    except OverflowError:   # 'cannot convert float infinity to integer', happens when price = inf
        price_string = 'infinite'
    except ValueError:      # 'cannot convert float NaN to integer', happens when passed inf/x
        price_string = 'infinite'

    return price_string


def generate_unique_id(recipe_id, other_recipe_id=0, size=0):
    from hashlib import blake2b
    key = (other_recipe_id).to_bytes(length=size, byteorder='big')
    msg = (recipe_id).to_bytes(length=size, byteorder='big')
    id_hash = blake2b(key=key, digest_size=size)
    id_hash.update(msg)
    unique_id = int.from_bytes(id_hash.digest(), byteorder='big')
    return unique_id


if __name__ == '__main__':
    init_items_flag = False
    init_recipes_flag = False
    
    if init_items_flag:
        init_items()
        populate_items()
        vendor_pricing()
        trading_post_pricing()
        
    db.query("VACUUM()")

    if init_recipes_flag:
        init_recipes()
        init_views)
        missed_recipes = populate_recipe_table()
        while missed_recipes:
            missed_recipes = populate_recipe_table(recipe_list=missed_recipes)

        db.query("VACUUM()")

    added_recipes = alternate_recipes(debug=True)
    while added_recipes:
        added_recipes = alternate_recipes(debug=True)

    recipe_list = api_query(payload='', endpoint='recipe_details')
    if verbose:
        print('evaluating profitable recipes')
    for recipe_id in recipe_list:
        get_price(recipe_id=recipe_id)
