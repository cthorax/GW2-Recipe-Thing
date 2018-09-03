
import pickle
import configparser
from collections import Counter

import records
import requests

config = configparser.ConfigParser()
config.read('config.ini')

karma_conversion = config['db_only']['karma_conversion']
init_items_flag = config['db_only'].getboolean('init_items_flag')
init_recipes_flag = config['db_only'].getboolean('init_items_flag')
add_alt_recipes = config['db_only'].getboolean('add_alt_recipes')
verbose = config['all_files'].getboolean('verbose')
db_url = config['all_files']['db_url']
db = records.Database(db_url=db_url)


def base36encode(number):
    """Converts an integer to a base36 string."""       # stolen from stackoverflow.com/questions/1181919/python-base-36-encoding
    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'

    if 0 <= number < len(alphabet):
        return alphabet[number]

    base36 = ''
    while number != 0:
        number, i = divmod(number, len(alphabet))
        base36 = alphabet[i] + base36

    return base36


def component_to_string(item_id, count):
    component_string = "!{ingredient_code}*{count},".format(ingredient_code=base36encode(item_id), count=count)
    return component_string


def string_to_component_dict_list(component_string):
    component_dict_list = []
    for component in component_string.split(','):
        if component == '':
            continue
        item_id, count = component.split('*')
        item_id = int(item_id[1:], 36)

        component_dict_list.append({'item_id': int(item_id), 'count': int(count)})
        
    return component_dict_list


def dict_list_to_string(recipe_dict_list):
    ingredients = Counter()
    for ingredient in recipe_dict_list:
        item_id = ingredient['item_id']
        quantity = ingredient['count']
        ingredients[item_id] += quantity

    component_string = ''
    for ingredient_id, ingredient_quantity in ingredients.most_common():
        component_string += component_to_string(item_id=ingredient_id, count=ingredient_quantity)
        
    return component_string


def combine_dict_list_to_string(list_of_dict_lists, item_to_remove=None):
    ingredients = Counter()
    for dict_list in list_of_dict_lists:
        for ingredient in dict_list:
            item_id = ingredient['item_id']
            if item_to_remove != item_id:
                quantity = ingredient['count']
                ingredients[item_id] += quantity

    component_string = ''
    for ingredient_id, ingredient_quantity in ingredients.most_common():
        component_string += component_to_string(item_id=ingredient_id, count=ingredient_quantity)

    return component_string


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
        assert isinstance(payload, (list, tuple))
        list_string = str(payload)[1:-1].replace(' ', '')    # strips '[' and ']' from str representation.
        url = "https://api.guildwars2.com/v2/items?ids={}".format(list_string)
    elif endpoint == 'multi_recipe':
        assert isinstance(payload, (list, tuple))
        list_string = str(payload)[1:-1].replace(' ', '')    # strips '[' and ']' from str representation.
        url = "https://api.guildwars2.com/v2/recipes?ids={}".format(list_string)
    elif endpoint == 'multi_pricing':
        assert isinstance(payload, (list, tuple))
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
    item_id INTEGER PRIMARY KEY,
    name TEXT,
    vendor_cost INTEGER DEFAULT 1234567890,
    karma_cost REAL DEFAULT 999999999999.0,
    vendor_value INTEGER DEFAULT 0,
    bound INTEGER,
    tp_cost INTEGER DEFAULT 1234567890,
    tp_value INTEGER DEFAULT 0
);""")
    db.query(query="INSERT INTO ITEMS (item_id, vendor_cost, karma_cost, vendor_value, bound, tp_cost, tp_value) VALUES (0, 0, 0, 0, 0, 0, 0);")


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
    SELECT item_id, name, tp_cost, vendor_cost, karma_cost,
        CASE WHEN tp_cost < vendor_cost AND tp_cost < karma_cost / {converter} THEN 'tp'
            WHEN vendor_cost <= tp_cost AND vendor_cost <= karma_cost / {converter} THEN 'vendor'
            WHEN karma_cost / {converter} < vendor_cost AND tp_cost >= karma_cost / {converter} THEN 'karma'
        ELSE 'none' END AS best_method,
        
        CASE WHEN tp_cost < vendor_cost AND tp_cost < karma_cost / {converter} THEN tp_cost
            WHEN vendor_cost <= tp_cost AND vendor_cost <= karma_cost / {converter} THEN vendor_cost
            WHEN karma_cost / {converter} < vendor_cost AND tp_cost >= karma_cost / {converter} THEN karma_cost
        ELSE 0 END AS best_cost
    FROM items""".format(converter=karma_conversion)
    db.query(query=create_string)


def populate_items(item_id_list=None):
    if item_id_list is None:
        item_id_list = api_query(payload='', endpoint='item_details')

    with_value_template = '{id}, "{name}", {value}, {bound}), ('
    without_value_template = '{id}, "{name}", {bound}), ('

    item_list_chunks = [item_id_list[x:x + 200] for x in range(0, len(item_id_list), 200)]      # 200 is max paging size per wiki on the api v2. this code stolen from stack exchange.
    for batch_number, chunk in enumerate(item_list_chunks):
        with_values_flag = False
        without_values_flag = False
        insert_string_with_value = "INSERT INTO items(item_id, name, vendor_value, bound) VALUES ("
        insert_string_without_value = "INSERT INTO items(item_id, name, bound) VALUES ("
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

    vacuum()


def vendor_pricing(vendor_dict=None):
    # dict must be of the form item_id: vendor price.
    if verbose:
        print('adding vendor pricing')

    if vendor_dict is None:
        with open('D:\STUFF I WROTE\GW2 Recipe Thing\\vendor_dict.pickle', 'rb') as itemlist_file:
            try:
                vendor_dict = pickle.load(file=itemlist_file)
            except FileNotFoundError:
                vendor_dict = {}

    update_cost_string = '''
    UPDATE items
    SET vendor_cost = {cost}
    WHERE item_id = {id};'''
    update_karma_string = '''
    UPDATE items
    SET karma_cost = {karma}
    WHERE item_id = {id};'''

    for item_id, costs in vendor_dict.items():
        vendor_cost = costs.get('vendor', None)
        karma_cost = costs.get('karma', None)
        if vendor_cost:
            db.query(query=update_cost_string.format(id=item_id, cost=vendor_cost))
        if karma_cost:
            db.query(query=update_karma_string.format(id=item_id, karma=karma_cost))

    vacuum()


def trading_post_pricing(item_list=None):
    if item_list is None:
        #todo get rid of this kludge holy shit
        item_list = eval(db.query('SELECT item_id FROM items;').export('csv').replace('\r\n', ', ')[9:])

    update_string ="UPDATE items SET tp_{type} = {cost} WHERE item_id = {id};"

    item_list_chunks = [item_list[x:x + 200] for x in range(0, len(item_list), 200)]      # 200 is max paging size per wiki on the api v2. this code stolen from stack exchange.
    for batch_number, chunk in enumerate(item_list_chunks, start=1):
        if verbose:
            print('\rupdating trading post pricing - chunk {current} of {total}'.format(current=batch_number, total=len(item_list_chunks)), end='')

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

    vacuum()


def populate_recipe_table(recipe_list=None):
    if recipe_list is None:
        recipe_list = api_query(payload='', endpoint='recipe_details')

    missed_recipes = recipe_list.copy()
    skip_recipes = []

    recipe_list_chunks = [recipe_list[x:x + 200] for x in range(0, len(recipe_list), 200)]      # 200 is max paging size per wiki on the api v2. this code stolen from stack exchange.
    for batch_number, chunk in enumerate(recipe_list_chunks, start=1):
        recipe_dict_list = api_query(payload=chunk, endpoint='multi_recipe')
        for recipe_number, recipe_dict in enumerate(recipe_dict_list, start=1):
            if verbose:
                print('\rpopulating recipe table - chunk {current_chunk} of {total_chunks} - recipe {current_recipe} of {total_recipes}'.format(
                    current_chunk=batch_number, total_chunks=len(recipe_list_chunks),
                    current_recipe=recipe_number, total_recipes=len(recipe_dict_list)
                ), end='')

            insert_string = """INSERT INTO recipes ( game_id, is_altered, unique_id, output_item, output_quantity, needs_recipe, component_string )
VALUES ( {id}, 0, {unique_id}, {output_id}, {output_quantity}, {needs_recipe}, '{component_string}' )"""

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

            component_string = dict_list_to_string(recipe_dict_list=recipe_dict.get('ingredients', []))

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

    vacuum()
    return missed_recipes


def alternate_recipes(debug=False):
    from math import gcd
    added_recipes = False
    if verbose:
        print("\radding alternate recipes", end='')

    component_recipe_result_dict_list = db.query("SELECT * FROM recipes ORDER BY is_altered ASC, game_id ASC;").as_dict()

    unique_id_list = []
    component_string_list = []
    for entry in component_recipe_result_dict_list:
        unique_id_list.append(entry['unique_id'])
        component_string_list.append(entry['component_string'])

    for component_recipe_number, component_recipe_dict in enumerate(component_recipe_result_dict_list, start=1):
        if verbose:
            print('\radding alternate recipes - component recipe:\t{component} of {max_components}'.format(
                component=component_recipe_number, max_components=len(component_recipe_result_dict_list)
            ), end='')
        component_recipe_unique_id = component_recipe_dict.get('unique_id')
        component_recipe_output_item = component_recipe_dict.get('output_item')
        component_recipe_output_quantity = component_recipe_dict.get('output_quantity')
        component_recipe_component_string = component_recipe_dict.get('component_string')
        component_output_search_string = component_to_string(item_id=component_recipe_output_item, count=0)[:-2]
        component_recipe_dict_list = string_to_component_dict_list(component_recipe_component_string)
        
        product_recipe_result_dict_list = db.query("SELECT * FROM recipes WHERE component_string LIKE '%{search}%'".format(search=component_output_search_string)).as_dict()
        for product_recipe_number, product_recipe_dict in enumerate(product_recipe_result_dict_list, start=1):
            if verbose:
                print('\radding alternate recipes - component recipe:\t{component} of {max_components} - product recipe:\t{product} of {max_products}'.format(
                        component=component_recipe_number, max_components=len(component_recipe_result_dict_list),
                        product=product_recipe_number, max_products=len(product_recipe_result_dict_list),
                ), end='')

            product_recipe_unique_id = product_recipe_dict.get('unique_id')
            combined_unique_id = generate_unique_id(product_recipe_unique_id, component_recipe_unique_id, size=7)
            if combined_unique_id in unique_id_list:
                continue
            else:
                product_recipe_game_id = product_recipe_dict.get('game_id')
                product_recipe_needs_recipe = product_recipe_dict.get('needs_recipe')
                product_recipe_output_item = product_recipe_dict.get('output_item')
                product_recipe_output_quantity = product_recipe_dict.get('output_quantity')
                product_recipe_string = product_recipe_dict.get('component_string', '')
                product_recipe_dict_list = string_to_component_dict_list(product_recipe_string)
            
                insert_string = """INSERT INTO recipes ( game_id, is_altered, needs_recipe, output_item, output_quantity, unique_id, component_string )
VALUES ( {game_id}, {is_altered}, {needs_recipe}, {output_item}, {output_quantity}, {unique_id}, '{component_string}' )"""

                for product_recipe_dict in product_recipe_dict_list:
                    if product_recipe_dict['item_id'] == component_recipe_output_item:
                        components_needed = product_recipe_dict['count']
                        break

                discrepancy_gcd = gcd(component_recipe_output_quantity, components_needed)
                component_multiplier = components_needed // discrepancy_gcd
                product_multiplier = component_recipe_output_quantity // discrepancy_gcd

                combined_recipe_string = combine_dict_list_to_string([product_recipe_dict_list]*product_multiplier + [component_recipe_dict_list]*component_multiplier, item_to_remove=component_recipe_output_item)
                combined_recipe_dict = {
                    'game_id': product_recipe_game_id,
                    'is_altered': 1,
                    'output_item': product_recipe_output_item,
                    'needs_recipe': product_recipe_needs_recipe,
                    'output_quantity': product_recipe_output_quantity * product_multiplier,
                    'unique_id': combined_unique_id,
                    'component_string': combined_recipe_string
                }

                if combined_recipe_string in component_string_list:
                    continue

                else:
                    db.query(insert_string.format(**combined_recipe_dict))
                    unique_id_list.append(combined_unique_id)
                    component_string_list.append(combined_recipe_string)
                    added_recipes = True

    if verbose:
        print(' - done.')

    return added_recipes


def best_recipe_by_recipe_id(recipe_id):
    output_item = db.query("SELECT output_item FROM recipes WHERE game_id = {recipe_id} LIMIT 1".format(recipe_id=recipe_id)).as_dict()
    try:
        output_item = output_item[0]['output_item']
        output_item_info = db.query("SELECT name, item_id, tp_value, vendor_value FROM items WHERE item_id = {item_id}".format(item_id=output_item)).as_dict()[0]
        alternate_recipe_dict_list = db.query("SELECT * FROM recipes WHERE game_id = {recipe_id}".format(recipe_id=recipe_id)).as_dict()
        output_dict = best_recipe_by_recipe_list(recipe_dict_list=alternate_recipe_dict_list, output_item_info=output_item_info)

        if output_dict:
            print("\nbest method for recipe {game_id}:\nprofit: {profit}\nmethod:{method}\n".format(**output_dict))
        else:
            if verbose:
                print('no profitable version of recipe {game_id}'.format(game_id=recipe_id))

        return None
    except LookupError:
        print('error in lookup for recipe {recipe_id}'.format(recipe_id=recipe_id))
        return True


def best_recipe_by_component(item_id):
    try:
        item_info = db.query("SELECT name, item_id, tp_value, vendor_value FROM items WHERE item_id = {item_id}".format(item_id=item_id)).as_dict()[0]
        if item_info['tp_value'] > item_info['vendor_value']:
            price_to_beat = item_info['tp_value']
            default_method = 'tp'
        else:
            price_to_beat = item_info['vendor_value']
            default_method = 'vendor'
        search_string = component_to_string(item_id=item_id, count=0)[:-2]
        recipe_list = db.query("SELECT * FROM recipes WHERE component_string LIKE '%{search}%'".format(search=search_string)).as_dict()
        output_dict = best_recipe_by_recipe_list(recipe_dict_list=recipe_list)

        if output_dict:
            for item in output_dict['raw_method']:
                if item['item'] == item_info['name']:
                    count = item['count']
                    break

            if price_to_beat < output_dict['raw_profit'] / count:
                output_string = "best recipe for item {name}:\nrecipe \{game_id\}:\nprofit: \{profit\}\nmethod:\{method\}\n".format(name=item_info['name'])
                print(output_string.format(**output_dict))

            else:
                print("just sell the {name} at {method} for {price}".format(name=item_info['name'], method=default_method, price=price_to_beat))
        else:
            print("just sell the {name} at {method} for {price}".format(name=item_info['name'], method=default_method, price=price_to_beat))
    except LookupError:
        print('lookup error on item {item_id}.'.format(item_id=item_id))


def best_recipe_by_recipe_list(recipe_dict_list, output_item_info=None):
    profit_dict_list = []
    for recipe_dict in recipe_dict_list:
        if output_item_info is None:
            output_item = recipe_dict['output_item']
            output_item_info = db.query("SELECT name, item_id, tp_value, vendor_value FROM items WHERE item_id = {item_id}".format(item_id=output_item)).as_dict()[0]

        ingredient_list = string_to_component_dict_list(recipe_dict['component_string'])
        output_count = recipe_dict['output_quantity']
        tp_revenue = output_item_info['tp_value'] * output_count
        vendor_revenue = output_item_info['vendor_value'] * output_count
        if tp_revenue > vendor_revenue:
            best_revenue = tp_revenue
            output_method_dict = {
                'type': 'sell',
                'count': output_count,
                'item': output_item_info['name'],
                'method': 'tp',
                'cost': format_prices(best_revenue)
            }
        else:
            best_revenue = vendor_revenue
            output_method_dict = {
                'type': 'sell',
                'count': output_count,
                'item': output_item_info['item_id'],
                'method': 'vendor',
                'cost': format_prices(best_revenue)
            }

        recipe_cost = 0
        recipe_method_dict_list = []
        for ingredient in ingredient_list:
            item_query = db.query("SELECT * FROM pricing WHERE item_id = {item_id}".format(item_id=ingredient['item_id'])).as_dict()[0]
            input_item_count = ingredient['count']
            best_item_cost = item_query['best_cost']
            best_total_cost = input_item_count * best_item_cost
            recipe_cost += best_total_cost

            alternate_recipe_method_dict = {
                'type': 'buy',
                'count': input_item_count,
                'item': item_query['name'],
                'method': item_query['best_method'],
                'cost': format_prices(best_total_cost)
            }
            recipe_method_dict_list.append(alternate_recipe_method_dict)
        recipe_method_dict_list.append(output_method_dict)

        alternate_recipe_profit = best_revenue - recipe_cost
        if alternate_recipe_profit > 0:
            profit_dict_list.append({'recipe_dict': recipe_dict, 'profit': alternate_recipe_profit, 'method': recipe_method_dict_list})

    if profit_dict_list:
        profit_dict_list = sorted(profit_dict_list, key=lambda x: x['profit'], reverse=False)
        profit_dict = profit_dict_list.pop()
        method_string = ''
        template = "\n• {type} {count} {item} at {method} for {cost}"
        for profit_method in profit_dict['method']:
            method_string += template.format(**profit_method)

        output_dict = {
            'game_id': profit_dict['recipe_dict']['game_id'],
            'method': method_string,
            'profit': format_prices(profit_dict['profit']),
            'raw_profit': profit_dict['profit'],
            'raw_method': profit_dict['method']
        }
        return output_dict

    else:
        return None


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


def vacuum():
    if verbose:
        from os.path import getsize
        before = getsize(db.db_url[10:])
        db.query('VACUUM;')
        after = getsize(db.db_url[10:])
        percentage = 1 - after/before
        print('db cleanup resulted in a {percentage:.3%} reduction in db size'.format(percentage=percentage))

    else:
        db.query('VACUUM;')


if __name__ == '__main__':
    if init_items_flag:
        init_items()
        populate_items()
        vendor_pricing()
        trading_post_pricing()
        init_views()
        vacuum()
        config['db_only']['init_items_flag'] = 'False'
        with open('config.ini', 'w') as config_file:
            config.write(config_file)

    if init_recipes_flag:
        init_recipes()
        missed_recipes = populate_recipe_table()
        while missed_recipes:
            missed_recipes = populate_recipe_table(recipe_list=missed_recipes)
            vacuum()
        config['db_only']['init_recipes_flag'] = 'False'
        with open('config.ini', 'w') as config_file:
            config.write(config_file)

    if add_alt_recipes:
        added_recipes = True
        while added_recipes:
            vacuum()
            added_recipes = alternate_recipes(debug=True)
        config['db_only']['add_alternate_recipes'] = 'False'
        with open('config.ini', 'w') as config_file:
            config.write(config_file)

    if init_items_flag is False and init_recipes_flag is False and add_alt_recipes is False:
        # trading_post_pricing()    #todo: activate this when live, disabled now for testing (don't need live prices to see if it's working)
        vacuum()

    item_id_list = api_query(payload='', endpoint='item_details')
    for item_id in item_id_list:
        best_recipe_by_component(item_id=item_id)

    recipe_list = api_query(payload='', endpoint='recipe_details')
    if verbose:
        print('evaluating profitable recipes')
    for recipe_id in recipe_list:
        missed_list = []
        missed = best_recipe_by_recipe_id(recipe_id=recipe_id)
        if missed is True:
            missed_list.append(recipe_id)

    if missed_list != []:
        populate_recipe_table(recipe_list=missed_list)
        vacuum()

