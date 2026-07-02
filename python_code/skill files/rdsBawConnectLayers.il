;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
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
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
procedure( bawConnectResonatorsForm()
    let((bawResAddConnectorField)

                  bawConnectorField = hiCreateStringField(
                        ?name 'bawResConnectHead
                        ?prompt "------------ Select MTE/MBE, Resonators and Generate ---------OK?----"
                        ?value  ""
                        ?defValue ""
                        ?editable nil
                  )
                  bawResAddConnectorField = hiCreateAppForm(
                        ?name 'bawResAddConnectF
                        ?formTitle "****** Generate BAW RES CONNECTORS ******"
                        ?buttonLayout 'OKCancelApply
                        ?callback "rdsBawConnectLayers()"
                        ?fields list(
                                                list(bawConnectorField 5:5 480:45 480)
                                        )
                  )

        hiDisplayForm(bawResAddConnectF)

    );let

);procedure


procedure( rdsBawConnectLayers()
prog((cv selList)
	;; Grab parametr from GUI
    cv = geGetEditCellView()	

    unless(member(cv->mode '("a" "w"))
		rdsBasePopupError("The cellview is read-only, please run the Utility on editable view!!")
		return( nil )
	);unless

    selList = geGetSelSet()
	;; Call rdsBawConnectLayers2 with arguments
    rdsBawConnectLayers2(cv selList)	
))


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;; $Id: rdsBawConnectLayers.il, v 1.0 2018/06/22 11:45:38 kotm Exp $
;; Revision 1.0 2018/06/22 11:45:38 kotm
;; "Initial Version"
;; Connect resonators 
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

procedure( rdsBawConnectLayers2(cv selList)
     prog( ( cN lN vN ncv ncN ncN2 icv icv2 ;;userName idNum
	     layerList ovlList bkN bkcv zcN zcv
	     AA BB BBresized CC DD JJ KK MM blN blN2 pts pts2 ptsL ptsL2 
	     allCells allCN inst tmpName1 tmpName2 tmpName3  a2 a3 a4 a5 a6 lm2 b2 b3 b4
		bawCells mysv mpad)

	;userName = getShellEnvVar("USER")
	;idNum    = 1000000
	;idNum    = random( idNum )
	;idNum    = sprintf(nil "%d" idNum)
;	      cv = geGetEditCellView()
	      cN = cv~>cellName
	      lN = cv~>libName
	      vN = cv~>viewName

;	 selList = geGetSelSet()
	     blN = nil
	    blN2 = nil
	    ptsL = nil
	   ptsL2 = nil
	      a2 = nil
	      a3 = nil
	      a4 = nil
	      a5 = nil	      

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

	;;;;;;;;;;;;;;;;To Remove existing Connect Cells if they are there;;;;;;;;;;;;;;;;;;;;;;;

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
;println("Check---01")
	    );;when
	    when( inst~>baseName=="myConnMBE" && inst~>cellName==tmpName2
	          dbDeleteObject( inst )
	          ddDeleteObj( ddGetObj( lN tmpName2 vN ) )
;println("Check---02")
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
	;;bkN  = strcat("con" "_" userName "_" idNum "_backup")
	bkN  = strcat(cN "_connect_backup")
	bkcv = dbOpenCellViewByType( lN bkN vN "maskLayout" "w" )
	printf("Backup Cell Name = %s\n" bkN) 
	foreach( shp bkcv~>shapes dbDeleteObject(shp) ) ;; clean up before copy
	foreach( itm selList 
		 ;if( ( itm~>objType=="polygon" && itm~>layerName=="BAW_MTE" ) ||
		 ;    ( itm~>objType=="polygon" && itm~>layerName=="BAW_MBE" )
		 ;    dbCopyFig( itm bkcv ) )
		 if( ( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_MTE" ) ||
		     ( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_MBE" ) ||
		     ( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_SV" ) 		
		     dbCopyFig( itm bkcv ) )
	);;foreach
	dbSave( bkcv )

;println("Check---A00")

	mysv = 0
	mpad = 0

when( blN
	;;;;;;;;;;;;;To Create New Cell Based on Connect Layer;;;;;;;;;;;;;;;;;;;
	ptsL = nil
	;;ncN  = strcat("conT" "_" userName "_" idNum)
	ncN  = strcat(cN "_connectMTE" )
	ncv  = dbOpenCellViewByType( lN ncN vN "maskLayout" "s" )
	printf("New Cell Name = %s\n" ncN) 
	foreach( shp ncv~>shapes dbDeleteObject(shp) ) ;; clean up before copy
	foreach( ins ncv~>instances dbDeleteObject(ins) ) ;; clean up before copy
	foreach( itm selList 
		 ;if( itm~>objType=="polygon" && itm~>layerName=="BAW_MTE" then
		 ;    dbCopyFig( itm ncv )
		 ;);;if
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_MTE" then
		     dbCopyFig( itm ncv )
		 );;if
		 if( itm~>objType=="inst" && rexMatchp( "^series$*" itm~>cellName ) then
		     dbCopyFig( itm ncv )
		 );;if
		 if( itm~>objType=="inst" && rexMatchp( "^shunt$*" itm~>cellName ) then
		     dbCopyFig( itm ncv )
		 );;if
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_SV" then
		     mysv = 1 
		     dbCopyFig( itm ncv )
		 );;if
		
	);;foreach
	dbSave( ncv )
	icv=dbOpenCellViewByType( lN ncN vN "maskLayout" "a" )
;println("Check---A01")

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
		       substring(inst~>cellName 1 5) =="shunt" 
		       dbFlattenInst( inst 32 t )
		 )
	);;foreach

;println("Check---A02")

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
	DD=dbLayerSize(icv "pin" CC 1.0)
	KK=dbLayerAndNot(icv "BAW_MTE" AA BBresized 1024)
	JJ=dbLayerAndNot(icv "BAW_MTE" KK DD 1024)
    unless(mysv == 0    
	MM = setof(shp icv~>shapes shp~>layerName=="BAW_NoMF5")
	dbLayerSize( icv "BAW_SV" MM 0.0 )
	foreach(shp MM dbDeleteObject(shp) )	
    );unless
;println("Check---A03")

	foreach(shp AA dbDeleteObject(shp) )	
	foreach(shp BB dbDeleteObject(shp) )	
    foreach(shp BBresized dbDeleteObject(shp) )
	foreach(shp CC dbDeleteObject(shp) )	
	foreach(shp DD dbDeleteObject(shp) )	
	foreach(shp KK dbDeleteObject(shp) )	

;; Remove small MTE pieces
	
;;	rdsRemoveSmallelem(icv lN ncN vN "BAW_MTE")
	
;println("Check---A04")

	;;;;;;;;;;;;;;;;;;;Layer Generation for the rest of the layers;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
	layerList=list("BAW_STE" "BAW_PZL" "BAW_M1" "BAW_M2" "BAW_ReF" "BAW_SV" "BAW_TFP"  "BAW_TFS"   "BAW_TF1" "BAW_TF2" "BAW_TF3" "BAW_TF4" "BAW_TF5"  "BAW_TF6"   "y2"  )
	ovlList  =list( 7.0       5.0       3.0      2.0      3.0       3.0       3.0         3.0          3.0       3.0      3.0       3.0	 3.0	   3.0       0.0  )

	for( j 0 length(layerList)-1
	     dbLayerSize(icv nth(j layerList) JJ nth(j ovlList) )
	)

;println("Check---A05")

	dbSave(icv)

	dbCreateInstByMasterName( cv lN ncN "layout" "myConnMTE" list(0 0) "R0" )

);;when

;println("Check---B00")

when( blN2
	;;;;;;;;;;;;;To Create New Cell Based on Connect Layer;;;;;;;;;;;;;;;;;;;
	;;ncN2 = strcat("conB" "_" userName "_" idNum)
	ncN2 = strcat(cN "_connectMBE")
	ncv2 = dbOpenCellViewByType( lN ncN2 vN "maskLayout" "s" )
	printf("New Cell Name2 = %s\n" ncN2) 
	foreach( shp ncv2~>shapes dbDeleteObject(shp) ) ;; clean up before copy
	foreach( ins ncv2~>instances dbDeleteObject(ins) ) ;; clean up before copy

;; Use baw2 to avoid RDS_CDS_TECH

;	bawCells = ddGetObj("baw2")~>cells
	bawCells = ddGetObj(getShellEnvVar("RDS_CDS_TECH"))~>cells
	foreach( itm selList 
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect") && itm~>layerName=="BAW_MBE" then
		     dbCopyFig( itm ncv2 )
		 );;if
		 if( itm~>objType=="inst" && rexMatchp( "^series$*" itm~>cellName ) then
		     dbCopyFig( itm ncv2 )
		 );;if
		 if( itm~>objType=="inst" && rexMatchp( "^shunt$*" itm~>cellName ) then
		     dbCopyFig( itm ncv2 )
		 );;if
		 if( itm~>objType=="inst" && rexMatchp("^pad$*" itm~>cellName) then
		     dbCopyFig( itm ncv2 )
		 );;if
		 if( itm~>objType=="inst" && rexMatchp("^ppd" itm~>cellName) then
		     dbCopyFig( itm ncv2 )
		 );;if
		 if( itm~>objType=="inst" && !member(itm~>cellName bawCells~>name) then
		     dbCopyFig( itm ncv2 )
		 );;if
	    unless(mysv == 1
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName=="BAW_SV" then
		     dbCopyFig( itm ncv2 )
		 );;if
		);unless

	);;foreach
	dbSave( ncv2 )
	icv2=dbOpenCellViewByType( lN ncN2 vN "maskLayout" "a" )

;println("Check---B01")

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

		 when( substring(inst~>cellName 1 3) =="pad"|| substring(inst~>cellName 1 3) =="ppd"|| !member(inst~>cellName bawCells~>name)
			dbFlattenInst( inst 32 t )
			mpad = 1
			);when
	); foreach
		when(mpad ==1
			a2 = setof(shp icv2~>shapes shp~>layerName=="text" && (length(shp~>theLabel)<=3 || rexMatchp("FRAME" shp~>theLabel) || shp~>theLabel == "G" || shp~>theLabel == "S"))	
			foreach(b2 a2 a3 = append1(a3 dbGetTrueOverlaps(icv2 b2~>bBox)))
			foreach(b3 a3 a4 = append1(a4 setof(shp b3 shp~>layerName == "BAW_M1")))
			a5 = foreach(b4 a4 dbLayerSize(icv2 "y2" b4 1))
		    );when

	foreach( inst icv2~>instances
		 when( substring(inst~>cellName 1 6) =="series" || 
		       substring(inst~>cellName 1 5) =="shunt" 
		       dbFlattenInst( inst 32 t )
		 )
	);;foreach

;println("Check---B02")

	foreach( shp icv2~>shapes
		 unless( shp~>layerName=="BAW_MBE" || shp~>layerName=="BAW_KEY" 
			 || shp~>layerName=="BAW_H1" || shp~>layerName=="y2" 
			 || shp~>layerName=="BAW_NoMF5"
		 dbDeleteObject(shp)
		 )
	)
	BB=setof(shp icv2~>shapes shp~>layerName=="BAW_MBE")
    ;; Shrink MBE of resonators -1um so that interconnect gets a 1um overlap with resonators
    BBresized = dbLayerSize(icv2 "BAW_MBE" BB -0.2)
	AA=setof(shp icv2~>shapes shp~>layerName=="BAW_KEY")
	CC=setof(shp icv2~>shapes shp~>layerName=="BAW_H1")
	DD=dbLayerSize(icv2 "pin" CC 1.0)
	KK=dbLayerAndNot(icv2 "BAW_MBE" AA BBresized 1024)
	JJ=dbLayerAndNot(icv2 "BAW_MBE" KK DD 1024)
	
    unless(mysv == 1
	MM = setof(shp icv2~>shapes shp~>layerName=="BAW_NoMF5")
	dbLayerSize( icv2 "BAW_SV" MM 0.0 )
	foreach(shp MM dbDeleteObject(shp) )	
    );unless	


;println("Check---B03")

	foreach(shp AA dbDeleteObject(shp) )	
	foreach(shp BB dbDeleteObject(shp) )	
    foreach(shp BBresized dbDeleteObject(shp) )	
	foreach(shp CC dbDeleteObject(shp) )	
	foreach(shp DD dbDeleteObject(shp) )	
	foreach(shp KK dbDeleteObject(shp) )	

;; Check small MBE areas

;;	rdsRemoveSmallelem(icv2 lN ncN2 vN "BAW_MBE")
	
	
;println("Check---B04")

	;;;;;;;;;;;;;;;;;;;Layer Generation for the rest of the layers;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
	layerList=list("BAW_M1" "BAW_M2" "BAW_ReF" "BAW_SV" "BAW_TFP" "BAW_TFS"  "BAW_TF1" "BAW_TF2" "BAW_TF3" "BAW_TF4" "BAW_TF5"  "BAW_TF6" )
	ovlList  =list( 3.0      2.0      3.0       3.0      3.0        3.0    	  3.0       3.0      3.0       3.0         3.0      3.0)

	for( i 0 length(layerList)-1
	     dbLayerSize(icv2 nth(i layerList) JJ nth(i ovlList) )
	)

        when(mpad == 1
		a6 = setof(shp icv2~>shapes shp~>layerName =="y2")
		lm2 = setof(shp icv2~>shapes shp~>layerName =="BAW_M2")
		foreach(b5 a5 dbLayerAndNot(icv2 "BAW_M2" lm2 a6 1024))
		foreach(shp lm2 dbDeleteObject(shp) )
		foreach(shp a6 dbDeleteObject(shp) )
	);when

;println("Check---B05")

	dbSave(icv2)

	dbCreateInstByMasterName( cv lN ncN2 "layout" "myConnMBE" list(0 0) "R0" )

);;when

;println("Check---C00")
	;;;;;;;;;;;;;;;;;;;Remove Polygons not needed ;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

	foreach( itm selList 
		 if( ( itm~>objType=="polygon" || itm~>objType=="rect" ) && itm~>layerName!="BAW_MB2" && itm~>layerName!="BAW_TXTMB2" then

			dbDeleteObject( itm ) )
	);;foreach

	dbSave( cv )

	return( t )

	);;prog

);;	

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
procedure( bawConnectModifyForm()
    let((bawResConnectModField)

                  bawConnectModField = hiCreateStringField(
                        ?name 'bawConnectModHead
                        ?prompt "------ Reverse Existing Connector to Original for Modification ------OK?"
                        ?value  ""
                        ?defValue ""
                        ?editable nil
                  )
                  bawResConnectModField = hiCreateAppForm(
                        ?name 'bawResConnectModF
                        ?formTitle "****** REVERSE TO ORIGINAL ******"
                        ?buttonLayout 'OKCancelApply
                        ?callback "rdsBawConnectModify()"
                        ?fields list(
                                                list(bawConnectModField 5:5 480:45 480)
                                        )
                  )

        hiDisplayForm(bawResConnectModF)

    );let

);procedure

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Resonator Connect Modification
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
procedure( rdsBawConnectModify(@optional (cv geGetEditRep())) 
    prog( ( cN lN vN aC becN tecN bkcN cvInst instID )

	;;cv = geGetEditCellView()

	unless(member(cv->mode '("a" "w"))
		rdsBasePopupError("The cellview is read-only, please run the Utility on editable view!!")
		return( nil )
	      );unless

	cN = cv~>cellName
	lN = cv~>libName
	vN = cv~>viewName
	aC = ddGetObj(lN)~>cells

	bkcN = sprintf(nil "%s_connect_backup" cN)
	becN = sprintf(nil "%s_connectMBE" cN)
	tecN = sprintf(nil "%s_connectMTE" cN)
	
;; if there's no *_connect_back cell, create one from connectMBE and connectMTE
	aa = setof(x aC rexMatchp(strcat(cN "_connect_backup") x~>name))  
	if( !aa then
		bkcv = dbOpenCellViewByType( lN bkcN vN "maskLayout" "w" )
		mbecN = dbOpenCellViewByType( lN becN vN )
		mtecN = dbOpenCellViewByType( lN tecN vN )
		polyList = setof(x mtecN~>shapes (x~>layerName == "BAW_MTE" && (x~>objType == "polygon" || x~>objType == "rect")) )
		polyList = append(polyList setof(x mbecN~>shapes (x~>layerName == "BAW_MBE" && (x~>objType == "polygon" || x~>objType == "rect")) ) )
		polyList = append(polyList setof(x cv~>shapes (x~>layerName == "BAW_SV" && (x~>objType == "polygon" || x~>objType == "rect")) ) )		
		foreach( itm polyList 	
		     dbCopyFig( itm bkcv ) 
		);;foreach
		dbSave( bkcv )
	);;if

	aC = ddGetObj(lN)~>cells
	
	foreach( inst cv~>instances
		 if( inst~>cellName == sprintf( nil "%s_connectMBE" cN ) then
		     dbDeleteObject( inst )
		 foreach( icell aC
		    when( becN==icell~>name
			  ddDeleteObj(icell)
		    );;when
		 );;foreach
		 );;if	
		 if( inst~>cellName == sprintf( nil "%s_connectMTE" cN ) then
		     dbDeleteObject( inst )
		 foreach( icell aC
		    when( tecN==icell~>name
			  ddDeleteObj(icell)
		    );;if
		 );;foreach
		 );;if	
	);;foreach

	foreach( icell aC
		 when( bkcN==icell~>name
		 cvInst = dbOpenCellViewByType( lN bkcN vN)
		 instID = dbCreateInst( cv cvInst nil list(0 0) "R0" 1)
		 dbFlattenInst(instID 2 t nil nil t t nil t)
		 ddDeleteObj(icell)
		 );;when
	);;foreach

	dbSave( cv )

	return( t )

    );;prog

);;procedure

procedure(rdsRemoveSmallelem(mycv lN ncn vN layer)
let((minMarea wid lpp mbelems elem bBox llx lly urx ury output layArea)

	minMarea = 50.0
	wid = geOpen( ?lib lN	?cell ncn ?view vN  ?mode "a")
	lpp = list(layer "drawing")
	
	mbelems =  setof(shp mycv~>shapes shp~>layerName==layer)
	
	foreach(elem mbelems
		bBox = elem~>bBox
		llx = xCoord(lowerLeft(bBox))
		lly = yCoord(lowerLeft(bBox))
		urx = xCoord(upperRight(bBox))
		ury = yCoord(upperRight(bBox))
		
		output = leComputeAreaDensity( hiGetCurrentWindow()
                          list( list(lpp) )
                          ?depth 31
                          ?region list(llx:lly urx:lly urx:ury llx:ury))
 		layArea = nth(2 car(output))
		
		if(layArea < minMarea then 
			dbDeleteObject(elem))
	 );foreach

	hiEnqueueCmd("hiDBoxOK(geDBox)")
	hiCloseWindow(wid)		

);let
);procedure

