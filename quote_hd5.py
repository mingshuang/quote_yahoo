#!/usr/bin/env python
# -*- coding:  utf-8 -*-
"""a collection tools for hd5 stock database 

    HD5 file structure (data_xx.h5) 
    /(RootGroup) 'xx A share'
    /SPLITS (Group) 'splits & dividends' 
    /SPLITS /code (Table) ' '
        -> (time,sd, ss, ssp, cd)
        here, sd: stock dividends, ss: stock splits
              ssp: stock splits price, cd: cash dividends
    /DAILY (Group) 'daily quote'
    /DAILY /code (Table) 'name' 
        -> (time, open, high, low, close, volume, sum)
    /MIN5 (Group) '5-minute quote'
    /MIN5 /code (Table) 'name' 
        -> (time, open, high, low, close, volume, sum) 
"""
# ============================================================================
# imports
# ============================================================================

import sys
import datetime as dt
import os
import logging

import numpy as np
import tables as tb
import plac

from tools import *
import fxj_parser as fpar 

__status__ = "prototype"

# ============================================================================
# defination
# ============================================================================
class DescQuote(tb.IsDescription):
    time  = tb.Time32Col(pos=0)      # Seconds since 1970.1.1): integer
    open  = tb.Float32Col(pos=1)     # open price: float
    high  = tb.Float32Col(pos=2)     # highest price: float
    low   = tb.Float32Col(pos=3)     # lowest price: float
    close = tb.Float32Col(pos=4)     # close price: float
    vol   = tb.UInt32Col(pos=5)      # volumn(100 share): 
    sum   = tb.Float32Col(pos=6)     # sum: float

class DescSPLITS(tb.IsDescription):
    """ struct: date, sending ratio(free), sending ratio (charged), 
        sending price, dividend
    """ 
    time  = tb.Time32Col(pos=0)      # seconds ince 1970.1.1): integer
    sd    = tb.Float32Col(pos=1)     # songgu ratio: float
    ss    = tb.Float32Col(pos=2)     # peigu ratio: float
    ssp   = tb.Float32Col(pos=3)     # peigu ratio: float
    cd    = tb.Float32Col(pos=4)     # dividend: float

class SymbolTable(tb.IsDescription):
    code   = tb.StringCol(8,pos=0)    # code('SH600000')       
    name   = tb.StringCol(8,pos=1)    # name('PuFaYinHang')      

MARKETS=['SH','SZ']
TYPE_DAILY='DAILY'
TYPE_MIN5 ='MIN5'
TYPE_SPLITS ='SPLITS'
TYPE_HD5 = [TYPE_DAILY,TYPE_MIN5,TYPE_SPLITS]
GRP_DAILY='/DAILY'
GRP_MIN5='/MIN5'
GRP_SPLITS='/SPLITS'
TYPE2GRP = {TYPE_DAILY:'/DAILY',
           TYPE_MIN5:'/MIN5',
           TYPE_SPLITS:'/SPLITS'}
TYPE2DESC = {TYPE_DAILY:DescQuote,
           TYPE_MIN5:DescQuote,
           TYPE_SPLITS:DescSPLITS}
TYPE2EXPECTEDROW = {TYPE_DAILY: 10000,
           TYPE_MIN5:10000,
           TYPE_SPLITS:200}
MK_SH = 'SH'
MK_SZ = 'SZ'
MK_INDEX={'SH':'SH000001','SZ':'SZ399001'} 

# ============================================================================
# functions
# ============================================================================


# ============================================================================
# Logging
# ============================================================================
# init logging
log = logging.getLogger('quote_hd5') 
log.setLevel(logging.INFO) 
# define a handler which writes INFO messages or higher to sys.stderr
console = logging.StreamHandler()
#console.setLevel(logging.DEBUG)

# set a format which is simpler for console use
# tell the handler to use this format
console.setFormatter(
        logging.Formatter('%(levelname)-8s %(message)s') ) 
# add the handler to the log 
log.addHandler(console)

# ============================================================================
# HD5 Class
# ============================================================================

class QuoteHD5():
    """ class of quote hd5 DB
    """
    def __init__(self, hd5_path):
        
        hd5_fn= [(MK_SH,'data_sh.h5'),(MK_SZ,'data_sz.h5')]
        self._hd5fp = {}
        self._last_update={}
        for m, x in hd5_fn:
            fn = os.path.join(hd5_path,x)
            if os.path.exists(fn):
                fp = tb.openFile(fn, 
                                mode='r+', 
                                rootuep="/", 
                                nodecachesize =1024)
                self._hd5fp[m] = fp 
                self._last_update[m] = fp.root._v_attrs.LAST_UPDATE
                log.debug('open hd5 file %s' %(x))
            else:
                #self._hd5fp[m] = none
                log.critical('hd5 file %s not exist' %(x))

    def close(self):
        for fp in self._hd5fp.values():
            log.debug('close hd5 file %s' %(fp.filename))
            fp.close()

    def get_lastupdate(self):
        rst =[]
        for mk in MARKETS:
            fp = self._hd5fp[mk]
            rst.append('last update date of %s:' %fp.filename)
            for grp in fp.walkGroups():
                tmp = '{0:7}: {1}'.format(grp._v_name, grp._v_attrs.LAST_UPDATE) 
                rst.append(tmp)
        print('\n'.join(rst))


    def create_hd5(self,name,title='',cache=1024):
        """ create new hd5  
        """
        filters = tb.Filters(complevel=1, 
                         complib='lzo', 
                         shuffle=True, 
                         fletcher32=False)
        
        hd5_fp = tb.openFile(name, 
                          mode="w", 
                          title= title, 
                          rootUEP="/", 
                          filters =filters, 
                          nodeCacheSize = cache) 
        hd5_fp.root._v_attrs.LAST_UPDATE = '' 

        dst_daily = hd5_fp.createGroup(hd5_fp.root, 
                            'DAILY', title='daily quote')
        dst_daily._v_attrs.LAST_UPDATE = '' 
        dst_5min = hd5_fp.createGroup(hd5_fp.root,
                            'MIN5', title='5-minute quote')
        dst_5min._v_attrs.LAST_UPDATE = '' 
        dst_splits = hd5_fp.createGroup(hd5_fp.root,
                            'SPLITS', title='splits & dividends')
        dst_splits._v_attrs.LAST_UPDATE = '' 
        
        return hd5_fp 
                 
    def get_lostdate(self, code=None):
        """check lost date of 5min DB in given hd5 database
        Note: 5min DB starts from 20051103
        SH index: SH000001, SZ index: SZ399001 
        
        @hd5: hd5 file name
        @code: stock to be checked. if is '', use index of SH or SZ market

        return a list of missing date 
        """

        if code is None:
            code = MK_INDEX[MK_SH]
        else:
            code = code.upper()
            #code = 'SZ399001'

        #tbl = fp_hd5.root.gMinute._f_getChild(code)
        mk = code[:2]
        try: 
            tbl = self._hd5fp[mk].getNode(GRP_MIN5, name=code)
        except (NoSuchNodeError, NameError):
            log.debug('code % not available in DB' %code)
            return None

        rec_days = set(map(dtnum2str,tbl[:]['time']))
        work_days = get_workingdays(
                        dtnum2str(tbl[0][0]),dtnum2str(tbl[-1][0]))
        lost_date = [x for x in work_days if x not in rec_days]
        self.lost_date = lost_date
        return lost_date

    def _append_quote(self,
                        data_type,
                        data_source,
                        checkorder=True):
        """append data into hd5 file 
        
        @data_type: data type of data source, 'DAILY', 'MIN5', 'SPLITS'
        @dad_source: data to be appended, iteratable, structure likes
            [code,numarray]
        @checkorder: if True, only allow to append data according to 
                   time order. if False, can append w/o order, means
                   later appended data can be earlier than existed data.
                   useed to 
        """
        
        count=[0,0]

        for code, data in data_source:
            count[0] += 1
            code = code.upper()
            mk=code[:2]
            if mk not in MARKETS:
                log.error('undefined code prefix %s' %code)
                continue
            fp = self._hd5fp[mk]
            
            grp = fp.getNode(TYPE2GRP[data_type])
            lupdate = grp._v_attrs.LAST_UPDATE
            start = dtstr2num(lupdate) if lupdate else 0

            if checkorder:
                rows = data[np.where(data['time'] >= start)]
                if len(rows) < 1:
                    log.debug(
                            '%s has no data later than %s' %(code, lupdate))
                    continue
            else:
                rows = data
                #TODO: process for data sanity check 
            
            try:
                tbl = fp.getNode(TYPE2GRP[data_type], name=code)
            except tb.NoSuchNodeError:
                log.debug('create new table for %s' %code)
                tbl = fp.createTable(
                           TYPE2GRP[data_type],
                           code, 
                           TYPE2DESC[data_type],
                           expectedrows = TYPE2EXPECTEDROW[data_type])
            tbl.append(rows)
            tbl.flush()
            count[1] += 1

            # update last_update
            if code in MK_INDEX.values():
                tmp = dtnum2str(rows[-1][0])
                tbl._v_parent._v_attrs.LAST_UPDATE = tmp
                fp.root._v_attrs.LAST_UPDATE = tmp
        
        if data_type == TYPE_SPLITS:
            tmp=dt.datetime.strftime(dt.date.today(),'%Y%m%d')
            for mk in MARKETS:
                self._hd5fp[mk].root.SPLITS._v_attrs.LAST_UPDATE = tmp

        log.info('%s of total %s stocks appended into DB' %(
                                                    count[1],count[0]))

    def dad2hd5(self,dad_path):
        """update quote DB

        @dad_path: path of dad files
        """
        w_days = get_workingdays(self._last_update[MK_SH])
        for day in w_days[1:]:
            dad_daily = os.path.join(dad_path,day+'.dad')
            dad_min = os.path.join(dad_path,day+'m.dad')
            for fn, data_type in [(dad_daily,TYPE_DAILY), 
                            (dad_min,TYPE_MIN5)]:
                 
                data_source = fpar.iter_parser(fn, out_dtfmt=None)
                if data_source:
                    log.info('update %s' %fn)
                    err = self._append_quote(data_type,data_source)
                    data_source.close()
                else:
                    log.error('source file error %s' %fn)

        # update splits data
        splits = os.path.join(dad_path,'split.pwr')
        data_source = fpar.iter_parser(splits, out_dtfmt=None)
        if data_source:
            log.info('update %s' %splits)
            err = self._append_quote(TYPE_SPLITS,data_source)
            data_source.close()
        else:
            log.error('Source file error %s' %fn)

    def sort_hd5(self):
        """sort hd5 files 
        """
        for fp in self._hd5fp.values():
            log.debug('Start sort %s' %fp.name )
            for node in fp.walkNodes():
                if isinstance(node,tb.table.Table):
                    rows = node.read()
                    rows.sort(order='time')
                    node.modifyRows(start=0,stop=-1,rows=rows)
            log.debug('Sort finished')        

    def read(self,code,db_type):
        """read all quote from HD5 and return numpy recarray

        @code: stock code, 'SH510051'
        @db_type: dialy or 5min data
        
        return: a numpy recarray if success, otherwise, None
        """

        fp = self._hd5fp[code[:2].upper()]
        try:
            tbl = fp.getNode(TYPE2GRP[db_type], name=code.upper())
            rows = tbl.read()
            return rows
        except tb.NoSuchNodeError:
            log.debug('%s not exist in DB' %code) 
            return None

    def extract(self,code_lst, fn,title=''):
        """extract some codes to a new hd5 file 
           
        @fn: new hd5 file name
        @title: title of new hd5
        @code_lst: code to be copied, if [], copy all
        """
        if len(code_lst)<1:
            log.warning('no input code')
            return
        if title=='':
            title=','.join(code_lst)
        log.debug('create new hd5 db: %s' %fn)                
        dst_fp = self.create_hd5(name=fn,title=title)
        count=[0,0] 
        for code in code_lst:
            code = code.upper()
            if (code[:2] not in MARKETS) or len(code) != 8:
                log.error('invalide code %s' %code)
                continue
            count[0] += 1
            src_fp = self._hd5fp[code[:2]]
            for grp in TYPE2GRP.values():
                try:
                    dst_grp = dst_fp.getNode(grp)
                    src_tbl = src_fp.getNode(grp,name=code)
                    src_tbl.copy(dst_grp,src_tbl.name,overwrite=True)
                    log.debug('copy %s: %s -> %s' %(code,grp,grp))
                    count[1] += 1
                except tb.NoSuchNodeError: 
                    log.debug('%s not exist in src %s ' %(code,grp))  
                    continue
                except:
                    (type, value, traceback) = sys.exc_info()
                    log.error('unexpected %s: %s' %(type,value))
                    continue
        dst_fp.close()     
        log.info('%s out of %s are extracted to %s' %(
                                                count[1],count[0],fn))                
        return
# ============================================================================
# main
# ============================================================================
@plac.annotations(    
    hd5path=("hd5 DB path", 'positional', None),
    update_l=("update DB from local dad path",'option','u',str,None,"DATAPATH"),
    update_r=("update DB from remote",'flag','U'),
    extract=("extract codes to a new hd5 DB, split code w/ ,",
                                    'option','e',str,None,"CODES"),
    outfn=("output DB name",'option','o',str,None,"OUTPUT"),
    debug=("debug mode",'flag','d'),
    lastupdate=("print last update date",'flag','l'),
    sort=("sort DB by time order",'flag','s'),
        )
def main(hd5path,update_l,update_r,extract,outfn,debug,lastupdate,sort):
    
    # Get the log
    log = logging.getLogger('quote_hd5')

    if debug:
        log.setLevel(logging.DEBUG) 
    
    # create file handler which logs even debug messages
    log_fn=os.path.join(hd5path,'data_h5.log')
    fh = logging.FileHandler(log_fn,'a')
    fmt = '%(asctime)s %(name)-12s: %(levelname)-8s %(message)s'
    fh.setFormatter(logging.Formatter(fmt))
    log.addHandler(fh)
     
    if update_l:
        db=QuoteHD5(hd5path)
        db.dad2hd5(update_l)
        db.close()
        return    
    if lastupdate:
        db=QuoteHD5(hd5path)
        db.get_lastupdate()
        db.close()
        return
    if extract:
        codes =extract.split(',')
        fn = outfn if outfn else codes[0]+'.h5'
        db=QuoteHD5(hd5path)
        db.extract(codes,fn)
        return
if __name__ == "__main__":
    plac.call(main)


