from sqlalchemy.util import asyncio
from database.models import Competitor, CompetitorSale
from crud.algorithms.models import CheckResult
from crud.bin import get_lower_bin, get_upper_bin, get_upper_bin_by_competitor
from datetime import datetime
import math


class ProfitIncreaseAlgorithm:
    def __init__(self, main_algo, sales_acceleration_algorithm):
        super().__init__()
        self.main_algo = main_algo
        self.sales_acceleration_algorithm = sales_acceleration_algorithm
        self.competitor_db: Competitor = None

    def add_to_path(func):
        def wrapper(self, *args, **kwargs):
            result: CheckResult = func(self, *args, **kwargs)
            if result.path is not None:
                self.main_algo.result.path += result.path
            if result.text is not None:
                self.main_algo.result.text += result.text
            if result.full_text is not None:
                self.main_algo.result.text = result.full_text
            return result.result

        return wrapper

    @add_to_path
    def our_position_is_higher_then_competitor(self):
        if self.main_algo.product_db.search_position < self.competitor_db.search_position:
            return CheckResult(full_text="Наша позиция выше в поисковой выдаче по ключевику, чем у лучшего конкурента",
                               result=True)
        else:
            return CheckResult(full_text="Наша позиция ниже в поисковой выдаче по ключевику, чем у лучшего конкурента",
                               result=False)

    @add_to_path
    def more_then_eight_positions(self):
        if self.competitor_db.search_position - self.main_algo.product_db.search_position > 8: # ??? > или >= ?
            return CheckResult(full_text="Наша позиция выше конкурента на более чем 8 позиций",
                               result=True)
        else:
            return CheckResult(full_text="Наша позиция выше конкурента на менее или равно 8 позициям",
                               result=False) 

    @add_to_path
    def date_change_price_competitor_more_then_three_days(self):
        if (datetime.now().date() - self.competitor_db.price_change_date).days > 3:
            return CheckResult(full_text="С даты изменения цены у конкурента прошло 3 и более дня",
                               result=True)
        else:
            return CheckResult(full_text="С даты изменения цены у конкурента НЕ прошло 3 и более дня",
                               result=False)

    @add_to_path
    def date_change_price_competitor_more_then_two_days(self):
        if (datetime.now().date() - self.competitor_db.price_change_date).days > 2:
            return CheckResult(full_text="С даты изменения цены у конкурента прошло 2 и более дня",
                               result=True)
        else:
            return CheckResult(full_text="С даты изменения цены у конкурента НЕ прошло 2 и более дня",
                               result=False)

    @add_to_path
    def is_our_sales_speed__greater_than__competitor_sales_speed(self):
        if self.main_algo.product_db.average_sales_speed > self.competitor_db.average_sales_speed:
            return CheckResult(path="Наша скорость продаж > скорости продаж конкурента", result=True)
        else:
            return CheckResult(path="Наша скорость продаж < скорости продаж конкурента", result=False)
    
    @add_to_path
    def is_best_competitor_price__greater__then_our_price(self):
        if self.main_algo.product_db_data.competitors[0].price > self.main_algo.product_db.last_price:
            return CheckResult(path="Цена конкурента > цена наша,",
                               result=True)
        else:
            return CheckResult(path="Цена конкурента <= цена наша,",
                               result=False)

    @add_to_path
    def our_price_greater_then_competitor_more_then_ten_perc(self):
        if (self.main_algo.product_db.last_price / self.main_algo.product_db_data.competitors[0].price) >= 1.1:
            return CheckResult(path="Наша цена > цены конкурента на более чем 10%",
                               result=True)
        else:
            return CheckResult(path="Наша цена <= цены конкурента на более чем 10%",
                               result=False)

    def run(self):
        if self.main_algo.has_best_competitor_link_and_stock():
            self.competitor_db = self.main_algo.product_db_data.competitors[0]
            if self.our_position_is_higher_then_competitor():
                if self.more_then_eight_positions():
                    if self.is_our_sales_speed__greater_than__competitor_sales_speed():
                        if self.date_change_price_competitor_more_then_three_days():
                            self.main_algo.set_new_price(math.ceil(self.main_algo.product_db.last_price * 1.02)) # по алго вроде как нужно 2% Поднимать, поднял просто бин выше текущего
                            self.main_algo.product_db_data.result.text += ('1. Целевая цена =  действующая цена, увеличенная на 2% с округлением вверх\n'
                                                                           '2. Начало метки "3B."\n')
                            self.main_algo.update_mark("3B")
                        else:
                            new_bin = get_upper_bin_by_competitor(self.main_algo.product_db.sku_id, self.competitor_db, self.main_algo.db)
                            self.main_algo.set_new_price(new_bin.to_value)
                            self.main_algo.product_db_data.result.text += ('1. Целевая цена = цена на бин выше, чем у конкурента\n'
                                                                           '2. Начало метки "3C."\n')
                            self.main_algo.update_mark("3C")
                    else:
                        if self.date_change_price_competitor_more_then_three_days():
                            if self.is_best_competitor_price__greater__then_our_price():
                                self.main_algo.set_new_price(math.floor(self.competitor_db.price-1))
                                self.main_algo.product_db_data.result.text += ('Конкурент ниже в выдаче с более высокой ценой подобную \
                                                                                позицию продает чаще, чем мы. Отметить управляющего магазина.')
                                self.main_algo.update_mark("3D")
                            else:
                                if self.our_price_greater_then_competitor_more_then_ten_perc():
                                    '''Целевая цена =  выше лучшего конкурента на 9%, округленную вниз. Метка ветки: "3E."'''
                                    self.main_algo.set_new_price(math.floor(self.competitor_db.price * 1.09))
                                    self.main_algo.update_mark("3E")
                                else:
                                    self.main_algo.set_new_price(math.floor(self.main_algo.product_db.last_price * 0.99))
                                    self.main_algo.product_db_data.result.text += ('1. Нашу действующую цену уменьшаем на 1%\n'
                                                                                   '2. Начало метки "3F."\n')
                                    self.main_algo.update_mark("3F")
                        else:
                            self.main_algo.set_new_price(self.competitor_db.price)
                            self.main_algo.product_db_data.result.text += ('1. Целевая цена = цена конкурента\n'
                                                                           '2. Начало метки "3G."\n')
                            self.main_algo.update_mark("3G")
                else:
                    if self.is_our_sales_speed__greater_than__competitor_sales_speed():
                        if self.date_change_price_competitor_more_then_three_days():
                            self.main_algo.set_new_price(math.ceil(self.main_algo.product_db.last_price * 1.01))
                            self.main_algo.product_db_data.result.text += ('1. Целевая цена = ОКРУГЛВВЕРХ(действующая цена + 1%)\n'
                                                                           '2. Начало метки "3H."\n')
                            self.main_algo.update_mark("3H")
                        else:
                            self.main_algo.set_new_price(math.floor(self.competitor_db.price))
                            self.main_algo.product_db_data.result.text += ('1. Целевая цена = цена конкурента\n'
                                                                           '2. Начало метки "3I."\n')
                            self.main_algo.update_mark("3I")
                    else:
                        if self.date_change_price_competitor_more_then_three_days():
                            self.main_algo.set_new_price(math.floor(self.main_algo.product_db.last_price * 0.98))
                            self.main_algo.product_db_data.result.text += ('1. Целевая цена = ОКРУГЛВНИЗ(действующая цена - 2%)\n'
                                                                           '2. Начало метки "3J."\n')
                            self.main_algo.update_mark("3J")
                        else:
                            self.main_algo.set_new_price(math.floor(self.competitor_db.price-1))
                            self.main_algo.product_db_data.result.text += ('1. Целевая цена = ОКРУГЛВНИЗ(цена конкурента - 1 руб)\n'
                                                                           '2. Начало метки "3K."\n')
                            self.main_algo.update_mark("3K")
            else:
                if self.is_our_sales_speed__greater_than__competitor_sales_speed():
                    self.competitor_db.last_delta_between_us_and_cmp = self.competitor_db.last_delta_between_us_and_cmp + 1
                    percent = (100 + self.competitor_db.last_delta_between_us_and_cmp)/100
                    new_price = math.ceil(self.competitor_db.price * percent)
                    self.main_algo.set_new_price(new_price)
                    self.main_algo.product_db_data.result.text += (f'1. Целевая цена = ОКРУГЛВВЕРХ(цена конкурента*(100 + дельта)%) ({self.competitor_db.price} * {percent})\n'
                                                                   '2. Начало метки "3L."\n')
                    self.main_algo.update_mark("3L")            
                else:
                    self.competitor_db.last_delta_between_us_and_cmp = self.competitor_db.last_delta_between_us_and_cmp - 1
                    percent = (100 + self.competitor_db.last_delta_between_us_and_cmp) / 100
                    new_price = math.ceil(self.competitor_db.price * percent)
                    self.main_algo.set_new_price(new_price)
                    self.main_algo.product_db_data.result.text += (f'1. Целевая цена = ОКРУГЛВНИЗ(цена конкурента*(100 + дельта)%) ({self.competitor_db.price} * {percent})\n'
                                                                   '2. Начало метки "3N."\n')
                    self.main_algo.update_mark("3N")
        else:
            if self.main_algo.has_info_about_deliveries():
                self.main_algo.minimization_overlap_oos_date_and_delivery_date() # set_new_price уже применяется внутри
                self.main_algo.product_db_data.result.text += ('1. Выбираем бин, который приведет к минимизации срока ухода в OOS\n'
                                                               '2. Начало метки "3A2."\n')
                self.main_algo.update_mark("3A1")
            else:
                new_bin = asyncio.run(get_upper_bin(self.main_algo.product_db, self.main_algo.db))
                self.main_algo.product_db_data.result.text += ('1. Выбираем бин ниже текущего\n'
                                                               '2. Начало метки "3A2."\n')
                self.main_algo.set_mark("3A2")
                self.main_algo.set_new_price(new_bin.to_value)

        if self.main_algo.product_db_data.result.product.sku.price.new > self.main_algo.product_db.min_price:
            self.main_algo.set_new_price(self.main_algo.product_db_data.result.product.sku.price.new)
            self.main_algo.product_db_data.result.text += ('Сохраняем бин, как планируемая цена к изменению.\n')

        self.sales_acceleration_algorithm.work_with_calendar_events_and_timer_discounts()
