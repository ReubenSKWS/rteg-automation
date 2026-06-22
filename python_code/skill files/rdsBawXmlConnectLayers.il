;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;; $Id: bawConnectResonators.il, v 1.0 2018/06/22 11:45:38 kotm Exp $
;; Revision 1.0 2018/06/22 11:45:38 kotm
;; "Initial Version"
;; Connect resonators 
;; To re-use this in Gen TEG utility, redefine rdsBawConnectLayers and rdsBawConnectLayers2
;; Add TF1~5 layers according to JH's requirement on 12/18/2018
;; 09/03/2019, updated by yangj1, add 0.2 um MBE/MTE gap fixing
;; 05/26/2020, by yangj1, when there's no backup cell, create one from connectMBE(MBE), connectMTE(MTE) and main die (SV)
;; Keep MB2 and TXTMB2 for Brian, 07/06/2020, by wangx11
;; 09/03/2020, modified for layout optimization doe 
;;          enable instance level interconnect. Eg. in top cellview, select instances contains resonators/utility 
;;               generated resonators + MBE/MTE shapes to get interconnects
;;          no back up, no reverse function
;;          delete _connectMBE/MTE cells, interconnect are flattened
;; 10/03/2020, by yangj1
;;          if rTEG-->flattern interconnect
;;          if main die-->keep mbe/mte connect and backup cells
;; 11/04/2020, by yangj1
;;          due to ADR settings, modified M1/M2/SV/TFS/TFP/ReF/TF1~6 
;; 01/09/2020, by yangj1, updated for b aw 25
;; 01/14/2021, by yangj1, add checkbox for flatten intercon cells
;;             updated Trim Layers sizing, instead of using dblayersize, use copy and change lpp, to avoid off grid sizing
;; 01/20/2021, by wangx11, add rcap and ADR sizing according to JH
;; 01/20/2021, by wangx11, add vtb 
;; 02/04/2021, by yangj1, remove vtb, (adding vtb is to fix STE layer issue, but it will cause a gap on M1)
;; 03/28/2023, by yangj1, for ADR mode, STE to MTE enclosure change from 7 to 5
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
procedure( rdsBawXmlConnectResonatorsForm()
    let((bawResAddConnectorField bawConFlat bawADR)

                  bawConnectorField = hiCreateStringField(
                        ?name 'bawResConnectHead
                        ?prompt "------------ Select MTE/MBE, Resonators and Generate ---------OK?----"
                        ?value  ""
                        ?defValue ""
                        ?editable nil
                  )
                  bawConFlat = hiCreateBooleanButton( ?name 'bawConFlat
                                          ?buttonText "Flattern _ConnectMBE/MTE cells"
                                            ?value nil
                                          ?defValue nil
                                      )          
                  bawADR = hiCreateBooleanButton( ?name 'bawADR
                                          ?buttonText "ADR"
                                            ?value nil
                                          ?defValue nil
                                      )	                 
                  bawResAddConnectorField = hiCreateAppForm(
                        ?name 'bawResAddConnectF
                        ?formTitle "****** Generate BAW RES CONNECTORS ******"
                        ?buttonLayout 'OKCancelApply
                        ?callback "form = hiGetCurrentForm()
                                    rdsBawXmlInterconnect(form)"
                        ?fields list(
                                                list(bawConnectorField 5:5 480:45 480)
                                                list(bawConFlat 70:35 450:35 250)
					;	list(bawADR	70:45 450:45 250)
                                        )
                  )

        hiDisplayForm(bawResAddConnectF)

    );let

);procedure


procedure( rdsBawXmlInterconnect(form)
	let( 	(cv selSets selList instList instcv flat Adr)
	;; Grab parametr from GUI
    cv = geGetEditCellView()	
    selSets = geGetSelSet()
    
    flat = form~>bawConFlat~>value
 ;   Adr = form~>bawADR~>value	    

    selList = list()
    instList = list()
    foreach( itm selSets
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && (itm~>layerName=="BAW_MTE" || itm~>layerName=="BAW_MBE" ) then
		 	selList = append(selList list(itm))
		 )

        if( itm~>objType=="inst" && (exists(x itm~>master~>instances~>cellName rexMatchp("^series*" x)) || exists(x itm~>master~>instances~>cellName rexMatchp("^shunt*" x)) || exists(x itm~>master~>instances~>cellName rexMatchp("^Res_$*"  x))  || exists(x itm~>master~>instances~>cellName rexMatchp("$*_cres*"  x)) || exists(x itm~>master~>instances~>cellName rexMatchp("^rcap"  x)) || exists(x itm~>master~>instances~>cellName rexMatchp("^se_cir*" x)) || exists(x itm~>master~>instances~>cellName rexMatchp("^sh_cir*" x)) ) then 
		 	instList = append(instList list(itm))
		 else
            if( itm~>objType=="inst" && ( rexMatchp("^series*" itm~>cellName) || rexMatchp("^shunt*" itm~>cellName)|| rexMatchp("^se_cir*" itm~>cellName) || rexMatchp("^sh_cir*" itm~>cellName) || 
		 		rexMatchp("^Res_$*" itm~>cellName) || rexMatchp("$*_cres*" itm~>cellName) || ( rexMatchp("pad" itm~>cellName) && !rexMatchp("padbe" itm~>cellName) ) || rexMatchp("ppd" itm~>cellName) || rexMatchp("pcard" itm~>cellName) ||  rexMatchp("^rcap*" itm~>cellName)|| (exists(x itm~>master~>instances~>cellName (  (rexMatchp("pad" x) && !rexMatchp("padbe" x) ) || rexMatchp("ppd" x) || rexMatchp("pcard" x) ))  && !exists(x itm~>master~>instances~>cellName rexMatchp("$*_cres*"  x))  )  ) then
		 	selList = append(selList list(itm))
		    )	
		 )		 
	);;foreach

    rdsBawXmlConnectLayers(cv selList flat)	
    foreach(inst instList
    	instcv = dbOpenCellViewByType(inst~>libName inst~>cellName "layout" "maskLayout" "a")
    	 allList = nconc(instcv~>shapes instcv~>instances) 
    	rdsBawXmlConnectLayers(instcv allList flat)
    );;foreach
   );;let
);;proc



;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;; $Id: rdsBawConnectLayers.il, v 1.0 2018/06/22 11:45:38 kotm Exp $
;; Revision 1.0 2018/06/22 11:45:38 kotm
;; "Initial Version"
;; Connect resonators 
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

procedure( rdsBawXmlConnectLayers(cv selList flat)
     prog( ( cN lN vN ncv pdkVer adrl itm msg adr ncN ncN2 icv icv2 ;;userName idNum
	     layerList ovlList bkN bkcv zcN zcv cell
	     AA BB BBresized CC DD JJ KK MM NN VV WW LL OO PP SS GG HH blN blN2 pts pts2 ptsL ptsL2 
	     allCells allCN inst tmpName1 tmpName2 tmpName3  a2 a3 a4 a5 a6 lm2 b2 b3 b4
		bawCells mysv mpad itmADR itemRADR instlist ccv M2Shps M1Shps)

	      cN = cv~>cellName
	      lN = cv~>libName
	      vN = cv~>viewName
	      pdkVer = getShellEnvVar(strcat("RDS_" upperCase(env(RDS_CDS_TECH)) "_VER"))

	instlist = nil
	ccv = rdsBawInsthier(cv instlist); cell masters in hierarchy
     
        adrl = list()
;        foreach(itm selList
	foreach(itm ccv
            if( itm~>objType=="inst" && ( rexMatchp( "^series*" itm~>cellName ) ||  rexMatchp( "^shunt*" itm~>cellName )|| rexMatchp("^se_cir*" itm~>cellName) || rexMatchp("^sh_cir*" itm~>cellName) ||  rexMatchp( "^rcap*" itm~>cellName ) || (rexMatchp("pad" itm~>cellName) && !rexMatchp("padbe" itm~>cellName) ) || rexMatchp("ppd" itm~>cellName) || rexMatchp("pcard" itm~>cellName) || rexMatchp("rel" itm~>cellName) || rexMatchp("^Res_$*" itm~>cellName) || rexMatchp("$*_cres_*" itm~>cellName) ) then

                ;;when(!rexMatchp( "^rcap$" itm~>cellName )  itmADR = dbFindProp(itm "ADR")~>value)
	            ;;when(rexMatchp( "^rcap$" itm~>cellName )  itemRADR = dbFindProp(itm "RelADR")~>value)
	            itmADR = dbFindProp(itm "ADR")~>value
	            itemRADR = dbFindProp(itm "RelADR")~>value

                if(itm && (itmADR == "TRUE"||itemRADR == "TRUE") then 

                    if(!member(t adrl) then adrl = append1(adrl t) )
                else
                    if(!member(nil adrl) then adrl = append1(adrl nil) )
                );;ifitm
            );;if
        );;foreach
        

        if( length(adrl) != 1 then
            msg = "ADR values of all resonators are not identical, please check your design."
            bawSprtErrorHandler(msg)
            return(nil)
        else
            adr = car(adrl)
        );;if

	     blN = nil
	    blN2 = nil
	    ptsL = nil
	   ptsL2 = nil
	      a2 = nil
	      a3 = nil
	      a4 = nil
	      a5 = nil	      

/*        if( rexMatchp("RTEG1" cN) || rexMatchp("RTEG2" cN) || rexMatchp("RTEGs" cN) ||rexMatchp("rTEG1" cN) || rexMatchp("rTEG2" cN) then
            rteg = t
        else
            rteg = nil
        )
*/        
	;;;;;;;;;;;;;To Get Connect Layer;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
	foreach( itm selList 
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_MTE" then
		      blN = "MTE"
			else
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_MBE" then
		     blN2 = "MBE"
		 );;if
		 );;if
	);;

	if( blN == nil && blN2 == nil then
	    rdsBasePopupMsg( "Nothing to generate. Please select BAW_MTE/BAW_MBE and resonators to generate connectors." )
	    return( nil )
	)

	;;;;;;;;;;;;;;;;To Remove existing Connect Cells if they are there;;;;;;;;;;

	tmpName1 = sprintf(nil "%s_connectMTE" cN)
	tmpName2 = sprintf(nil "%s_connectMBE" cN)
	tmpName3 = sprintf(nil "%s_connect_backup" cN)

	allCN    = nil	
	allCells = ddGetObj( lN )~>cells
	foreach( cell allCells
		 allCN = append1( allCN cell~>name )
	)

	foreach( inst cv~>instances
	    when( inst~>baseName=="myConnMTE" && inst~>cellName==tmpName1
	          dbDeleteObject( inst )
	          ddDeleteObj( ddGetObj( lN tmpName1 vN ) )
	          ddDeleteObj( ddGetObj( lN tmpName3 vN ) )
	    );;when
	    when( inst~>baseName=="myConnMBE" && inst~>cellName==tmpName2
	          dbDeleteObject( inst )
	          ddDeleteObj( ddGetObj( lN tmpName2 vN ) )
	    );;when
	);;foreach
	    when( member( tmpName3 allCN )
		  ddDeleteObj( ddGetObj( lN tmpName3 vN ) )
	    )
	    when( member( tmpName1 allCN )
		  ddDeleteObj( ddGetObj( lN tmpName1 vN ) )
	    )
	    when( member( tmpName2 allCN )
		  ddDeleteObj( ddGetObj( lN tmpName2 vN ) )
	    )
	;;remove all cells with "connect" extensions


	;;;;;;;;;;;;;;;To Keep Back up cell for MTE/MBE polygon;;;;;;;;;;;;;;;;;;;;
	;;;;;;;;;;;;;;;Only do it for main die
	if( !flat  then
	    bkN  = strcat(cN "_connect_backup")
	    bkcv = dbOpenCellViewByType( lN bkN vN "maskLayout" "w" )
	    foreach( shp bkcv~>shapes dbDeleteObject(shp) ) ;; clean up before copy
	    foreach( itm selList 
		     if( ( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_MTE" ) ||
		         ( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_MBE" ) ||
		         ( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_SV" ) 		
		         dbCopyFig( itm bkcv ) )
	    );;foreach
	    dbSave( bkcv )
    );;if!flat

	mysv = 0
	mpad = 0

when( blN
	;;;;;;;;;;;;;To Create New Cell Based on Connect Layer;;;;;;;;;;;;;;;;;;;
	ptsL = nil
	;;ncN  = strcat("conT" "_" userName "_" idNum)
	ncN  = strcat(cN "_connectMTE" )
	ncv  = dbOpenCellViewByType( lN ncN vN "maskLayout" "s" )
	foreach( shp ncv~>shapes dbDeleteObject(shp) ) ;; clean up before copy
	foreach( ins ncv~>instances dbDeleteObject(ins) ) ;; clean up before copy
	foreach( itm selList 
		 ;if( itm~>objType=="polygon" && itm~>layerName=="BAW_MTE" then
		 ;    dbCopyFig( itm ncv )
		 ;);;if
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_MTE" then
		     dbCopyFig( itm ncv )
		 );;if
		 if( itm~>objType=="inst" && ( rexMatchp( "^series*" itm~>cellName ) || 
		    rexMatchp( "^shunt*" itm~>cellName ) || rexMatchp("^se_cir*" itm~>cellName) || rexMatchp("^sh_cir*" itm~>cellName)||  rexMatchp( "^rcap*" itm~>cellName ) ||
		    rexMatchp("^Res_$*" itm~>cellName) || rexMatchp("$*_cres_*" itm~>cellName) )  	then	    
		    
		     dbCopyFig( itm ncv )
		 );;if

        
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_SV" then
		     mysv = 1 
		     dbCopyFig( itm ncv )
		 );;if
		
	);;foreach
	dbSave( ncv )
	icv=dbOpenCellViewByType( lN ncN vN "maskLayout" "a" )


	foreach( shape icv~>shapes 
		 if( ( shape~>objType=="polygon" || shape~>objType=="rect" ) &&
		     shape~>layerName=="BAW_MTE" then
			dbLayerSize( icv "BAW_KEY" list(shape) 0.0 )
			dbDeleteObject(shape)
		 );if
	);;foreach
	foreach( shape icv~>shapes
	    unless(mysv == 0 
		 if( ( shape~>objType=="polygon" || shape~>objType=="rect" ) &&
		     shape~>layerName=="BAW_SV" then
			dbLayerSize( icv "BAW_NoMF5" list(shape) 0.0 )
			dbDeleteObject(shape)
		 );if	
	    );unless	
	);;foreach
	foreach( inst icv~>instances
		 when( substring(inst~>cellName 1 6) =="series" || 
		       substring(inst~>cellName 1 5) =="shunt" || 
		       substring(inst~>cellName 1 6) =="se_cir" || 
		       substring(inst~>cellName 1 6) =="sh_cir" || 
		 		substring(inst~>cellName 1 4) =="Res_"  || 
		 		rexMatchp("$*_cres_*" inst~>cellName)||rexMatchp("^rcap*" inst~>cellName)
		       dbFlattenInst( inst 32 t )
		 )
	);;foreach


	foreach( shp icv~>shapes
		 unless( shp~>layerName=="BAW_MTE" || shp~>layerName=="BAW_KEY" 
			 || shp~>layerName=="BAW_H1" || shp~>layerName=="BAW_NoMF5" 
		 dbDeleteObject(shp)
		 )
	)

	BB=setof(shp icv~>shapes shp~>layerName=="BAW_MTE")
    ;; Shrink MTE of resonators -1um so that interconnect gets a 1um overlap with resonators
    	BBresized = dbLayerSize(icv "BAW_MTE" BB -0.2)
	AA=setof(shp icv~>shapes shp~>layerName=="BAW_KEY")
	CC=setof(shp icv~>shapes shp~>layerName=="BAW_H1")
	
	if(adr  then
		DD=dbLayerSize(icv "pin" CC 4.0); 1.0->4.0
	  else
		DD=dbLayerSize(icv "pin" CC 1.0); 1.0->4.0
	);if		
	KK=dbLayerAndNot(icv "BAW_MTE" AA BBresized 1024)
	JJ=dbLayerAndNot(icv "BAW_MTE" KK DD 1024)
    unless(mysv == 0    
	    MM = setof(shp icv~>shapes shp~>layerName=="BAW_NoMF5")
	    dbLayerSize( icv "BAW_SV" MM 0.0 )
	    foreach(shp MM dbDeleteObject(shp) )	
    );unless
    
    NN = dbLayerSize(icv "BAW_MTE" BB 3.0)
    VV = dbLayerSize(icv "BAW_MTE" BB 1.2)
    WW = dbLayerSize(icv "BAW_MTE" BB 0.8)

    
	foreach(shp AA dbDeleteObject(shp) )	
	foreach(shp BB dbDeleteObject(shp) )	
;;    foreach(shp BBresized dbDeleteObject(shp) )
	foreach(shp CC dbDeleteObject(shp) )	
	foreach(shp DD dbDeleteObject(shp) )	
	foreach(shp KK dbDeleteObject(shp) )	



	;;;;;;;;;;;;;;;;;;;Layer Generation for the rest of the layers;;;;;;;;;;;;;;
;;    layerList=list("BAW_STE" "BAW_PZL" "BAW_M1"    "BAW_M2" "BAW_ReF" "BAW_SV" "BAW_TFP"  "BAW_TFS"   "BAW_TF1" "BAW_TF2" "BAW_TF3" "BAW_TF4" "BAW_TF5"  "BAW_TF6"   "y2"  )
;;    ovlList  =list( 7.0       5.0       3.0      2.0      3.0       3.0       3.0         3.0          3.0       3.0      3.0       3.0	    3.0	        3.0       0.0  )

	layerList=list(     "BAW_STE" "BAW_PZL"  "y2"    "BAW_SV"   "BAW_M1"    "BAW_M2"    "BAW_ReF"  "BAW_TFP"  "BAW_TFS"   "BAW_TF1" "BAW_TF2" "BAW_TF3" "BAW_TF4" "BAW_TF5"  "BAW_TF6"     )
;;  ovlList  =list(     7.0       5.0        0.0      3.0           3.0        2.0        3.0       3.0         3.0          3.0       3.0      3.0       3.0	    3.0	        3.0   )

    if( adr then

 ;;JH       ovlList  =list( 7.0       5.0        0.0        3.0        3.0       2.0        0.0        0.0        0.0           0.0      0.0       0.0	     0.0	 0.0          0.0)
;;JH 		ovlList  =list( 7.0       5.0        0.0        3.0        3.0       2.0        0.0        0.0        0.0           0.0      0.0       0.0	     0.0	 0.0          0.0)
;;          ovlList  =list( 7.0       4.0        0.0        2.0        2.0       1.0        0.0        0.0        0.0           0.0      0.0       0.0	     0.0	 0.0          0.0)
;;baw2 5 v1.06, STE enclosure change from 7 to 5
            ovlList  =list( 5.0       4.0        0.0        2.0        2.0       1.0        0.0        0.0        0.0           0.0      0.0       0.0	     0.0	 0.0          0.0)
        ;;refer to          mte       mte        mte        mte         mte       mte       m1        m1          m1            m1        m1        m1        m1      m1          m1          
        ;;m1Ovl = 2.0; 3.0->2.0  
        ;;m2Ovl = 1.0; 2.0->1.0
        ;;m1Ovl = 3.0   ;;Matt 05/26/2021     
        ;;m2Ovl = 2.0
        m1Ovl = 2.0   ;;JH 01/20/2023    
        m2Ovl = 1.0
        GG = dbLayerSize(icv "BAW_M1" JJ m1Ovl 1024)
        HH = dbLayerAndNot(icv "BAW_M1" GG VV 1024)
        ;;sv is the same oversize as m1, so use GG
        PP = dbLayerAndNot(icv "BAW_SV" GG NN 1024)
        OO = dbLayerSize(icv "BAW_M2" HH -1.0 1024)
    ;;    LL = dbLayerAndNot(icv "BAW_M2" OO WW 1024)
        
	    for( j 0 2
	        dbLayerSize(icv nth(j layerList) JJ nth(j ovlList) 1024)
	    )
	    for( j 6 length(layerList)-1
;;	        dbLayerSize(icv nth(j layerList) HH nth(j ovlList) 1024)
            foreach(ele HH
                cpele = dbCopyShape(ele icv list(0:0 "R0" 1) )
                cpele~>lpp = list(nth(j layerList) "drawing")
            );;foreach
	    )	
        foreach(shp GG dbDeleteObject(shp) )    
      ;;  foreach(shp OO dbDeleteObject(shp) )      
            
    else
	    ovlList  =list( 7.0       5.0       0.0      3.0      3.0      2.0       3.0       3.0         3.0          3.0       3.0      3.0       3.0	    3.0	        3.0  )
	    for( j 0 length(layerList)-1
            dbLayerSize(icv nth(j layerList) JJ nth(j ovlList) )	        
	    )
    );;if


    foreach(shp BBresized dbDeleteObject(shp) )
    foreach(shp NN dbDeleteObject(shp) )
    foreach(shp VV dbDeleteObject(shp) )   
    foreach(shp WW dbDeleteObject(shp) ) 
    
    ;;remove M1/M2 small pieces (<36/42.25 um^2)
    M2Shps=setof(shp icv~>shapes shp~>layerName=="BAW_M2")
    M1Shps=setof(shp icv~>shapes shp~>layerName=="BAW_M1")
    foreach(shp M2Shps if( shp~>objType == "line" || rdsCalcArea(shp) < 42.25 then dbDeleteObject(shp) ) )
    foreach(shp M1Shps if( shp~>objType == "line" || rdsCalcArea(shp) < 36 then dbDeleteObject(shp) ) )
    
	dbSave(icv)

	dbCreateInstByMasterName( cv lN ncN "layout" "myConnMTE" list(0 0) "R0" )

);;when


when( blN2
	;;;;;;;;;;;;;To Create New Cell Based on Connect Layer;;;;;;;;;;;;;;;;;;;
	;;ncN2 = strcat("conB" "_" userName "_" idNum)
	ncN2 = strcat(cN "_connectMBE")
	ncv2 = dbOpenCellViewByType( lN ncN2 vN "maskLayout" "s" )
	foreach( shp ncv2~>shapes dbDeleteObject(shp) ) ;; clean up before copy
	foreach( ins ncv2~>instances dbDeleteObject(ins) ) ;; clean up before copy

;; Use bawpdk4 to avoid RDS_CDS_TECH

	bawCells = ddGetObj("bawpdk4")~>cells
	foreach( itm selList 
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect") && itm~>layerName=="BAW_MBE" then
		     dbCopyFig( itm ncv2 )
		 );;if
	 
		 
		 if( itm~>objType=="inst" && ( rexMatchp( "^series*" itm~>cellName ) || 
		    rexMatchp( "^shunt*" itm~>cellName )|| rexMatchp("^se_cir*" itm~>cellName) || rexMatchp("^sh_cir*" itm~>cellName) ||  
		    rexMatchp("^Res_$*" itm~>cellName) || rexMatchp("$*_cres_*" itm~>cellName) ||  (rexMatchp("pad" itm~>cellName) && !rexMatchp("padbe" itm~>cellName) ) || rexMatchp("ppd" itm~>cellName) || rexMatchp("pcard" itm~>cellName) ||rexMatchp( "^rcap*" itm~>cellName )||
		    (exists(x itm~>master~>instances~>cellName (  (rexMatchp("pad" x) && !rexMatchp("padbe" x) ) || rexMatchp("ppd" x) || rexMatchp("pcard" x)) )  && !exists(x itm~>master~>instances~>cellName rexMatchp("$*_cres*"  x)))   ) then
		     dbCopyFig( itm ncv2 )	     
		 );;if

/*
		 if( itm~>objType=="inst" && rexMatchp("pad$*" itm~>cellName) then
		     dbCopyFig( itm ncv2 )
		 );;if
		 if( itm~>objType=="inst" && !member(itm~>cellName bawCells~>name) then
		     dbCopyFig( itm ncv2 )
		 );;if
*/		 
	    unless(mysv == 1
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_SV" then
		     dbCopyFig( itm ncv2 )
		 );;if
		);unless

	);;foreach
	dbSave( ncv2 )
	icv2=dbOpenCellViewByType( lN ncN2 vN "maskLayout" "a" )


	foreach( shape icv2~>shapes 
		 if( ( shape~>objType=="polygon" || shape~>objType=="rect" ) &&
		     shape~>layerName=="BAW_MBE" then
			dbLayerSize( icv2 "BAW_KEY" list(shape) 0.0 )
			dbDeleteObject(shape)
		 );if
	);foreach
	foreach( shape icv2~>shapes 
	    unless(mysv == 1			
		 if( ( shape~>objType=="polygon" || shape~>objType=="rect" ) &&
		     shape~>layerName=="BAW_SV" then
			dbLayerSize( icv2 "BAW_NoMF5" list(shape) 0.0 )
			dbDeleteObject(shape)
		 );if	
	    );unless	
	);;foreach

    foreach( inst icv2~>instances
		 when( (rexMatchp("pad" inst~>cellName) && !rexMatchp("padbe" inst~>cellName) )  || rexMatchp("ppd" inst~>cellName) || rexMatchp("pcard" inst~>cellName)		 		
		       dbFlattenInst( inst 32 t )
		 )
	);;foreach
    foreach( inst icv2~>instances	
		 when(exists(x inst~>master~>instances~>cellName (   ( rexMatchp("pad" x) && !rexMatchp("padbe" x) ) || rexMatchp("ppd" x) || rexMatchp("pcard" x) ))  && !exists(x inst~>master~>instances~>cellName rexMatchp("$*_cres*"  x))
		        dbFlattenInst( inst 32 t )
		 )
	);;foreach	
	foreach( shp icv2~>shapes
		 unless(shp~>layerName=="BAW_KEY" 
			 || shp~>layerName=="BAW_H1" || shp~>layerName=="y2" 
			 || shp~>layerName=="BAW_NoMF5" || shp~>layerName=="BAW_H5"
		 dbDeleteObject(shp)
		 )
	)	
/*
	foreach( inst icv2~>instances

		 when( substring(inst~>cellName 1 3) =="pad"|| !member(inst~>cellName bawCells~>name)
			dbFlattenInst( inst 32 t )
			mpad = 1
			);when
	); foreach
		when(mpad ==1
			a2 = setof(shp icv2~>shapes shp~>layerName=="text" && length(shp~>theLabel)<=3)	
			foreach(b2 a2 a3 = append1(a3 dbGetTrueOverlaps(icv2 b2~>bBox)))
			foreach(b3 a3 a4 = append1(a4 setof(shp b3 shp~>layerName == "BAW_M1")))
			a5 = foreach(b4 a4 dbLayerSize(icv2 "y2" b4 1))
		    );when
*/

	foreach( inst icv2~>instances
		 when( substring(inst~>cellName 1 6) =="series" || 
		       substring(inst~>cellName 1 5) =="shunt" ||		       
		       substring(inst~>cellName 1 6) =="se_cir" || 
		       substring(inst~>cellName 1 6) =="sh_cir" || 
		 		substring(inst~>cellName 1 4) =="Res_"  || 
		 		rexMatchp("$*_cres_*" inst~>cellName) || rexMatchp("^rcap*" inst~>cellName)	 		
		       dbFlattenInst( inst 32 t )
		 )
	);;foreach


	foreach( shp icv2~>shapes
		 unless( shp~>layerName=="BAW_MBE" || shp~>layerName=="BAW_KEY" 
			 || shp~>layerName=="BAW_H1" || shp~>layerName=="y2" 
			 || shp~>layerName=="BAW_NoMF5" || shp~>layerName=="BAW_H5"
		 dbDeleteObject(shp)
		 )
	)
	
	
	BB=setof(shp icv2~>shapes shp~>layerName=="BAW_MBE")
    ;; Shrink MBE of resonators -1um so that interconnect gets a 1um overlap with resonators
    BBresized = dbLayerSize(icv2 "BAW_MBE" BB -0.2)
	AA=setof(shp icv2~>shapes shp~>layerName=="BAW_KEY")
	CC=setof(shp icv2~>shapes shp~>layerName=="BAW_H1")
	if(adr then
		DD=dbLayerSize(icv2 "pin" CC 4.0); 1.0->4.0
	  else
		DD=dbLayerSize(icv2 "pin" CC 1.0); 1.0->4.0
	);if	
;**	DD=dbLayerSize(icv2 "pin" CC 4.0); 1.0->4.0
	KK=dbLayerAndNot(icv2 "BAW_MBE" AA BBresized 1024)
	JJ=dbLayerAndNot(icv2 "BAW_MBE" KK DD 1024)
	
    unless(mysv == 1
	    MM = setof(shp icv2~>shapes shp~>layerName=="BAW_NoMF5")
	    dbLayerSize( icv2 "BAW_SV" MM 0.0 )
	    foreach(shp MM dbDeleteObject(shp) )	
    );unless	
    
    NN = dbLayerSize(icv2 "BAW_MTE" BB 3.0)
    VV = dbLayerSize(icv2 "BAW_MTE" BB 1.2)
    WW = dbLayerSize(icv2 "BAW_MTE" BB 0.8)
    QQ = setof(shp icv2~>shapes shp~>layerName=="BAW_H5")    
    RR = dbLayerSize(icv2 "BAW_H5" QQ 1.0 )  
        
	foreach(shp AA dbDeleteObject(shp) )	
	foreach(shp BB dbDeleteObject(shp) )	
;;    foreach(shp BBresized dbDeleteObject(shp) )	
	foreach(shp CC dbDeleteObject(shp) )	
	foreach(shp DD dbDeleteObject(shp) )	
	foreach(shp KK dbDeleteObject(shp) )	



	;;;;;;;;;;;;;;;;;;;Layer Generation for the rest of the layers;;;;;;;;;;;;;;
;;	layerList=list("BAW_M1" "BAW_M2" "BAW_ReF" "BAW_SV" "BAW_TFP" "BAW_TFS"  "BAW_TF1" "BAW_TF2" "BAW_TF3" "BAW_TF4" "BAW_TF5"  "BAW_TF6" )
;;    ovlList  =list( 3.0      2.0      3.0       3.0      3.0        3.0    	  3.0       3.0      3.0       3.0         3.0      3.0)
	layerList=list("BAW_SV" "BAW_M1" "BAW_M2"   "BAW_ReF" "BAW_TFP" "BAW_TFS"  "BAW_TF1" "BAW_TF2" "BAW_TF3" "BAW_TF4" "BAW_TF5"  "BAW_TF6" )
;;    ovlList  =list( 3.0     3.0      2.0         3.0      3.0        3.0    	  3.0       3.0      3.0       3.0         3.0      3.0)    
;printf("adr is %L" adr)
    if( adr  then
        ovlList  =list( 3.0     3.0      2.0         0.0      0.0        0.0    	  0.0       0.0      0.0       0.0         0.0      0.0) 
        m1Ovl = 2.0 ; 3.0->2.0  
        m2Ovl = 1.0; 2.0->1.0
        GG = dbLayerSize(icv2 "BAW_M1" JJ m1Ovl 1024)
        HH = dbLayerAndNot(icv2 "BAW_M1" GG VV 1024)
        PP = dbLayerAndNot(icv2 "BAW_SV" GG NN 1024)
        OO = dbLayerSize(icv2 "BAW_SV" JJ m2Ovl 1024)        
     ;; LL = dbLayerAndNot(icv2 "BAW_M2" OO WW 1024)
        LL = dbLayerSize(icv2 "BAW_M2" HH -1.0 1024)
        SS = dbLayerAndNot(icv2 "BAW_M2" LL RR 1024)
        
              
        for( i 3 length(layerList)-1
;;            dbLayerSize(icv2 nth(i layerList) HH nth(i ovlList)  )
            foreach(ele HH
                cpele = dbCopyShape(ele icv2 list(0:0 "R0" 1) )
                cpele~>lpp = list(nth(i layerList) "drawing")
            );;foreach
	    )
	    foreach(shp GG dbDeleteObject(shp) )    
	    foreach(shp OO dbDeleteObject(shp) )   
        foreach(shp LL dbDeleteObject(shp) ) 
    else
        ovlList  =list( 3.0      3.0      2.0       3.0      3.0        3.0    	  3.0       3.0      3.0       3.0         3.0      3.0)
	    for( i 0 length(layerList)-1
            sizeShp = dbLayerSize(icv2 nth(i layerList) JJ nth(i ovlList) )
	        if( nth(i layerList) == "BAW_M2" then
	            dbLayerAndNot(icv2 "BAW_M2" sizeShp RR 1024)
	            foreach(shp sizeShp dbDeleteObject(shp) ) 
	        );;if
	    );for
    );;if
    
    foreach(shp BBresized dbDeleteObject(shp) )	
    foreach(shp NN dbDeleteObject(shp) )
    foreach(shp VV dbDeleteObject(shp) )
    foreach(shp WW dbDeleteObject(shp) )
    foreach(shp QQ dbDeleteObject(shp) )
    foreach(shp RR dbDeleteObject(shp) )	

/*
        when(mpad == 1
		a6 = setof(shp icv2~>shapes shp~>layerName =="y2")
		lm2 = setof(shp icv2~>shapes shp~>layerName =="BAW_M2")
		foreach(b5 a5 dbLayerAndNot(icv2 "BAW_M2" lm2 a6 1024))
		foreach(shp lm2 dbDeleteObject(shp) )
		foreach(shp a6 dbDeleteObject(shp) )
	);when
*/

    ;;remove M1/M2 small pieces (<36/42.25 um^2)
    M2Shps=setof(shp icv2~>shapes shp~>layerName=="BAW_M2")
    M1Shps=setof(shp icv2~>shapes shp~>layerName=="BAW_M1")
    foreach(shp M2Shps if( shp~>objType == "line" || rdsCalcArea(shp) < 42.25 then dbDeleteObject(shp) ) )
    foreach(shp M1Shps if( shp~>objType == "line" || rdsCalcArea(shp) < 36 then dbDeleteObject(shp) ) )
    
	dbSave(icv2)

	dbCreateInstByMasterName( cv lN ncN2 "layout" "myConnMBE" list(0 0) "R0" )

);;when

	;;;;;;;;;;;;;;;;;;;Remove Polygons not needed ;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

	foreach( itm selList 
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName!="BAW_MB2" && itm~>layerName!="BAW_TXTMB2" then

			dbDeleteObject( itm ) )
	);;foreach

    
    ;;;;;;;; if rteg-->flatten interconnect cells ;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
    ;;;;;;;; if main die, keep mbe/mte_conn, and backup cells ;;;;;;;;;;;;;;;;;;
    ;;;;;;;; updated, flat = rteg
	;;;;;;;;;;;;;;;;;;;;;;;;;;;flatten interconnects;;;;;;;;;;;;;;;;;;;;;;;;;;;;
	
	if(flat  then	
	    myConnect = setof(x cv~>instances rexMatchp("_connectMBE" x~>cellName) || rexMatchp("_connectMTE" x~>cellName))
	
	    foreach(conn myConnect  dbFlattenInst( conn 1 nil )  )

	    dbSave( cv )

	    if( ddGetObj(lN  ncN2 vN) then  ddDeleteObj(ddGetObj(lN  ncN2 vN)))
        if( ddGetObj(lN  ncN vN)  then  ddDeleteObj(ddGetObj(lN  ncN vN)))
    else
        dbSave(cv)
    );if

	return( t )

	);;prog

);;	

procedure(rdsBawInsthier(cv instlist)
prog((inst instm)
    foreach(inst cv~>instances
	    instlist = append1(instlist inst)	
	);foreach
    foreach(inst cv~>instances
	    instm = inst~>master
	    instlist = rdsBawInsthier(instm instlist)	
	);foreach		

	return(instlist)
))

